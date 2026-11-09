"""Synthetic installation-driver contracts; never install or infer in unit tests."""
import errno
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import time
from types import SimpleNamespace

import pytest

SOURCE = Path(__file__).parents[1]/'tools/windows_installer_acceptance.py'
spec=importlib.util.spec_from_file_location('windows_installer_acceptance',SOURCE)
accept=importlib.util.module_from_spec(spec);spec.loader.exec_module(accept)


def test_nsis_destination_is_last_unquoted_and_unicode_spaces_are_preserved():
    command=accept.nsis_command(r'C:\build folder\WeCFU setup.exe',r'C:\Temp\WeCFU 安装 test\isolated')
    assert command=='"C:\\build folder\\WeCFU setup.exe" /S /D=C:\\Temp\\WeCFU 安装 test\\isolated'
    assert '/NCRC' not in command
    for path in ('relative', 'C:\\x" /R', 'C:\\x\n', 'C:\\trailing '):
        with pytest.raises(RuntimeError):accept.nsis_command(r'C:\build\setup.exe',path)


def make_payload(root):
    files={'runtime/python.exe':b'fake CPython','app/desktop_entry.py':b'fake entry',
           'models/pinned.bin':b'fake model bytes'}
    for relative,raw in files.items():
        path=root/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
    manifest={'schema_version':1,'platform':'win32-x64','app_version':'synthetic',
              'python':'runtime/python.exe','entrypoint':'app/desktop_entry.py',
              'files':{name:hashlib.sha256(raw).hexdigest() for name,raw in files.items()}}
    raw=json.dumps(manifest).encode();(root/'bundle-manifest.json').write_bytes(raw)
    return raw


@pytest.mark.parametrize('mutation',['changed','missing','extra','manifest','junction'])
def test_installed_payload_uses_source_manifest_and_exact_file_inventory(tmp_path,monkeypatch,mutation):
    raw=make_payload(tmp_path);deadline=time.monotonic()+5
    assert accept.verify_payload(tmp_path,raw,deadline)['files']==3
    if mutation=='changed':(tmp_path/'models/pinned.bin').write_bytes(b'wrong')
    if mutation=='missing':(tmp_path/'app/desktop_entry.py').unlink()
    if mutation=='extra':(tmp_path/'unlisted.py').write_bytes(b'executable')
    if mutation=='manifest':(tmp_path/'bundle-manifest.json').write_bytes(raw+b' ')
    if mutation=='junction':
        original=accept.is_link
        monkeypatch.setattr(accept,'is_link',lambda path:path==tmp_path/'models' or original(path))
    with pytest.raises(RuntimeError):accept.verify_payload(tmp_path,raw,deadline)


def test_manifest_rejects_duplicate_and_case_colliding_paths(tmp_path):
    raw=make_payload(tmp_path)
    with pytest.raises(RuntimeError,match='Duplicate'):
        accept.manifest_document(raw.replace(b'"schema_version": 1',b'"schema_version":1,"schema_version":1'))
    value=json.loads(raw);value['files']['APP/desktop_entry.py']=value['files']['app/desktop_entry.py']
    with pytest.raises(RuntimeError,match='Case-colliding'):accept.manifest_document(json.dumps(value).encode())
    value=json.loads(raw);value['files']['../outside']='0'*64
    with pytest.raises(RuntimeError,match='Unsafe'):accept.manifest_document(json.dumps(value).encode())


class Key:
    def __init__(self,path):self.path=path
    def __enter__(self):return self
    def __exit__(self,*args):pass


class Registry:
    HKEY_CURRENT_USER='user';HKEY_LOCAL_MACHINE='machine'
    KEY_WOW64_32KEY=32;KEY_WOW64_64KEY=64;KEY_READ=1
    def __init__(self,match=False,denied=False):self.match=match;self.denied=denied
    def OpenKey(self,hive,path,*args):
        if self.denied:raise PermissionError(errno.EACCES,'synthetic registry read denied')
        if path==accept.UNINSTALL:return Key(path)
        if isinstance(hive,Key) and path=='opaque-id':return Key(path)
        raise FileNotFoundError(path)
    def QueryInfoKey(self,key):return (1,0,0)
    def EnumKey(self,key,index):return 'opaque-id'
    def QueryValueEx(self,key,field):
        if field=='DisplayName':return ('WeCFU' if self.match else 'Other app',1)
        raise FileNotFoundError(field)


def test_existing_registration_paths_and_unreadable_registry_are_fail_closed(tmp_path):
    deadline=time.monotonic()+5
    env={'LOCALAPPDATA':str(tmp_path)}
    assert accept.preflight_existing(Registry(),env,deadline)['registrations']==[]
    with pytest.raises(RuntimeError,match='Existing'):
        accept.preflight_existing(Registry(match=True),env,deadline)
    with pytest.raises(PermissionError):accept.preflight_existing(Registry(denied=True),env,deadline)
    (tmp_path/'WeCFU').mkdir()
    with pytest.raises(RuntimeError,match='Existing'):
        accept.preflight_existing(Registry(),env,deadline)
    assert (tmp_path/'WeCFU').is_dir()  # No delete/uninstall behavior.


def test_hashing_respects_total_deadline(tmp_path):
    source=tmp_path/'file';source.write_bytes(b'bytes')
    with pytest.raises(RuntimeError,match='1200-second'):accept.digest(source,time.monotonic()-1)


@pytest.mark.parametrize('failure',[False,True])
def test_owned_job_is_retired_after_success_or_timeout(tmp_path,monkeypatch,failure):
    from wecfu import platform_runtime
    events=[]
    class Pipe:
        def close(self):events.append('stdin_closed')
    class Process:
        stdin=Pipe()
        def wait(self,timeout):
            assert 0<timeout<=300
            if failure:raise subprocess.TimeoutExpired('synthetic installer',timeout)
            return 0
    process=Process()
    monkeypatch.setattr(platform_runtime,'spawn_owned',lambda *a,**k:process)
    monkeypatch.setattr(platform_runtime,'stop_owned',lambda p,timeout:events.append(('retired',p)))
    call=lambda:accept.run_owned(['fake','-B','wrapper'],tmp_path,time.monotonic()+500,300,'synthetic')
    if failure:
        with pytest.raises(subprocess.TimeoutExpired):call()
    else:
        assert call()['exit_code']==0
    assert events==['stdin_closed',('retired',process)]


def test_nonwindows_refuses_without_spawning_or_installing(tmp_path,monkeypatch):
    monkeypatch.setattr(accept.sys,'platform','darwin')
    monkeypatch.setattr(accept,'run_owned',lambda *a,**k:pytest.fail('nonwindows must not execute'))
    monkeypatch.setattr(accept.sys,'argv',['script','--installer','fake.exe','--built-exe','app.exe',
        '--source-bundle','source','--output',str(tmp_path/'evidence')])
    assert accept.main()==1
    record=json.loads((tmp_path/'evidence/result.json').read_text())
    assert record['status']=='failed' and 'Windows-only' in record['error']
