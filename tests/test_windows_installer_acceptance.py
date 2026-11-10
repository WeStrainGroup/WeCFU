"""Synthetic installation-driver contracts; never install or infer in unit tests."""
import errno
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import shutil
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


def test_nsis_identity_is_full_hash_of_only_fixed_marker_change_across_chunk_boundary(tmp_path):
    built=tmp_path/'wecfu-desktop.exe'
    original=b'MZ' + b'x'*(1024**2-13) + accept.UNKNOWN_BUNDLE_MARKER + b'rest-of-executable'
    expected=original.replace(accept.UNKNOWN_BUNDLE_MARKER,accept.NSIS_BUNDLE_MARKER,1)
    built.write_bytes(original)
    identity=accept.nsis_shell_identity(built,time.monotonic()+5)
    assert identity['expected_installed_sha256']==hashlib.sha256(expected).hexdigest()
    assert identity['original_sha256']==hashlib.sha256(original).hexdigest()
    assert identity['bytes']==len(original)==len(expected)
    assert identity['marker_offset']==original.index(accept.UNKNOWN_BUNDLE_MARKER)
    assert built.read_bytes()==original
    destination=tmp_path/'installed';destination.mkdir()
    (destination/built.name).write_bytes(expected)
    (destination/'uninstall.exe').write_bytes(b'uninstaller')
    receipt={}
    assert accept.verify_installed_shell(destination,built,identity,time.monotonic()+5,receipt)==destination/built.name
    assert set(receipt['non_bundle_installed_files'])=={built.name,'uninstall.exe'}


@pytest.mark.parametrize('mutation',['wrong-name','unpatched','other-byte','changed-size'])
def test_nsis_shell_rejects_any_other_identity_and_retains_root_inventory(tmp_path,mutation):
    built=tmp_path/'wecfu-desktop.exe';original=b'MZ'+accept.UNKNOWN_BUNDLE_MARKER+b'executable'
    built.write_bytes(original);identity=accept.nsis_shell_identity(built,time.monotonic()+5)
    expected=original.replace(accept.UNKNOWN_BUNDLE_MARKER,accept.NSIS_BUNDLE_MARKER)
    destination=tmp_path/'installed';destination.mkdir()
    name='WeCFU.exe' if mutation=='wrong-name' else built.name
    actual=original if mutation=='unpatched' else b'NZ'+expected[2:] if mutation=='other-byte' else expected+b'!' if mutation=='changed-size' else expected
    (destination/name).write_bytes(actual)
    receipt={}
    with pytest.raises(RuntimeError):
        accept.verify_installed_shell(destination,built,identity,time.monotonic()+5,receipt)
    assert receipt['non_bundle_installed_files']=={name:hashlib.sha256(actual).hexdigest()}
    assert receipt['installed_exe']['exists']==(mutation!='wrong-name')
    assert (destination/name).read_bytes()==actual


@pytest.mark.parametrize('markers',[b'no-known-marker',accept.UNKNOWN_BUNDLE_MARKER*2])
def test_nsis_identity_rejects_unknown_or_duplicate_marker(tmp_path,markers):
    built=tmp_path/'app.exe';built.write_bytes(b'MZ'+markers)
    with pytest.raises(RuntimeError,match='Duplicate build' if markers==accept.UNKNOWN_BUNDLE_MARKER*2 else 'Missing build'):
        accept.nsis_shell_identity(built,time.monotonic()+5)


@pytest.mark.parametrize('change',[b'altered',b''])
def test_nsis_identity_rejects_build_mutation_between_scan_and_derived_hash(tmp_path,monkeypatch,change):
    built=tmp_path/'app.exe';original=b'MZ'+accept.UNKNOWN_BUNDLE_MARKER+b'payload';built.write_bytes(original)
    real_open=Path.open;reads=0
    def changing_open(path,*args,**kwargs):
        nonlocal reads
        if path==built and args and args[0]=='rb':
            reads+=1
            if reads==2:
                with real_open(path,'wb') as stream:stream.write(b'MZ'+accept.UNKNOWN_BUNDLE_MARKER+change)
        return real_open(path,*args,**kwargs)
    monkeypatch.setattr(Path,'open',changing_open)
    with pytest.raises(RuntimeError,match='changed'):
        accept.nsis_shell_identity(built,time.monotonic()+5)


def test_nsis_identity_pins_both_lock_and_actual_cli_version(tmp_path):
    lock=tmp_path/'desktop/package-lock.json';lock.parent.mkdir()
    cli=tmp_path/'desktop/node_modules/@tauri-apps/cli/package.json';cli.parent.mkdir(parents=True)
    lock.write_text(json.dumps({'packages':{'node_modules/@tauri-apps/cli':{'version':'2.12.4'}}}))
    cli.write_text(json.dumps({'version':'2.12.4'}))
    assert accept.check_bundler_version(tmp_path)==[lock,cli]
    for modified in (cli,lock):
        before=modified.read_bytes();modified.write_bytes(before.replace(b'2.12.4',b'2.12.5'))
        with pytest.raises(RuntimeError,match='Unreviewed'):accept.check_bundler_version(tmp_path)
        modified.write_bytes(before)


@pytest.mark.parametrize('mutation', ['none', 'retry', 'evidence'])
def test_complete_installed_receipt_handles_utf8_under_windows_legacy_locale(tmp_path, monkeypatch, mutation):
    """Exercise the final gate with fake installation/inference, including Unicode.

    This deliberately models CP1252 defaults on every host, so a macOS developer
    cannot accidentally accept a locale-dependent receipt reader again.
    """
    source = tmp_path/'source'; source.mkdir(); raw = make_payload(source)
    installer = tmp_path/'setup.exe'; installer.write_bytes(b'synthetic installer')
    built = tmp_path/'wecfu-desktop.exe'
    built.write_bytes(b'MZ'+accept.UNKNOWN_BUNDLE_MARKER+b'synthetic executable')
    install_parent = tmp_path/'WeCFU install 验证'; install_parent.mkdir()
    destination = install_parent/'WeCFU isolated'
    output = tmp_path/'evidence'
    lock = tmp_path/'lock.json'; lock.write_text('{}', encoding='utf-8')

    monkeypatch.setattr(accept.sys, 'platform', 'win32')
    monkeypatch.setitem(accept.sys.modules, 'winreg', Registry())
    monkeypatch.setattr(accept, 'preflight_existing', lambda *args: {'registrations': [], 'present_paths': []})
    monkeypatch.setattr(accept, 'check_bundler_version', lambda repo: [lock])
    monkeypatch.setattr(accept.tempfile, 'mkdtemp', lambda **kwargs: str(install_parent))
    monkeypatch.setattr(accept, 'nsis_command', lambda exe, dest: 'synthetic installer command')
    monkeypatch.setattr(accept.sys, 'argv', ['script', '--installer', str(installer), '--built-exe', str(built),
        '--source-bundle', str(source), '--output', str(output)])
    real_read = Path.read_text
    def legacy_read(path, encoding=None, errors=None):
        return real_read(path, encoding=encoding or 'cp1252', errors=errors)
    monkeypatch.setattr(Path, 'read_text', legacy_read)

    def simulated_process(command, folder, deadline, cap, name):
        if name == 'installer':
            destination.mkdir()
            shutil.copytree(source, destination/'bundle')
            (destination/built.name).write_bytes(built.read_bytes().replace(accept.UNKNOWN_BUNDLE_MARKER, accept.NSIS_BUNDLE_MARKER))
        else:
            assert name == 'installed-api'
            api = output/'installed-api'; api.mkdir()
            evidence = api/'synthetic.log'; evidence.write_bytes(b'completed synthetic workflow')
            result = {
                'status': 'passed', 'mode': 'two_image_real_SAM', 'explicit_synthetic': True,
                'real_model_requests': 2, 'real_model_request_attempts': 3 if mutation == 'retry' else 2,
                'manifest_sha256': hashlib.sha256(raw).hexdigest(), 'app_version': 'synthetic',
                'actual_runtime': {'executable': str(destination/'bundle/runtime/python.exe')},
                'files': {evidence.name: hashlib.sha256(evidence.read_bytes()).hexdigest()},
            }
            encoded = json.dumps(result, ensure_ascii=False).encode('utf-8')
            with pytest.raises(UnicodeDecodeError): encoded.decode('cp1252')
            (api/'result.json').write_bytes(encoded)
            if mutation == 'evidence': evidence.write_bytes(b'changed after receipt')
        return {'exit_code': 0, 'seconds': 0, 'timeout_seconds': cap}
    monkeypatch.setattr(accept, 'run_owned', simulated_process)
    from tools import windows_shell_smoke
    def simulated_shell(executable, bundle, manifest, folder, expected, deadline):
        assert executable == destination/built.name and bundle == destination/'bundle'
        assert expected == hashlib.sha256(executable.read_bytes()).hexdigest()
        return {'mode': 'installed_shell_boot_and_forced_owned_cleanup', 'model_requests': 0}
    monkeypatch.setattr(windows_shell_smoke, 'run', simulated_shell)

    assert accept.main() == (0 if mutation == 'none' else 1)
    receipt = json.loads((output/'result.json').read_text(encoding='utf-8'))
    assert receipt['installed_payload']['files'] == 3
    assert receipt['installed_exe']['sha256'] == receipt['installed_exe']['expected_sha256']
    if mutation == 'none':
        assert receipt['status'] == 'passed'
        assert receipt['installed_shell_receipt']['model_requests'] == 0
        assert '验证' in receipt['installed_api_receipt']['actual_runtime']['executable']
    else:
        assert receipt['status'] == 'failed'
        assert receipt['error_type'] == 'RuntimeError'
        assert ('required complete' if mutation == 'retry' else 'evidence changed') in receipt['error']
