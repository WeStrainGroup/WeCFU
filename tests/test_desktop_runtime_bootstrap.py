"""Bundled-runtime preparation: synthetic files/probes, no install or ML imports."""
import hashlib
import io
import json
from pathlib import Path
import sys
import pytest
from wecfu import runtime_bootstrap as bootstrap
from wecfu import runtime_paths, setup_models, platform_runtime


@pytest.fixture
def bundle(monkeypatch, tmp_path):
    monkeypatch.setenv('WECFU_DESKTOP_MANAGED', '1')
    monkeypatch.setattr(bootstrap.sys, 'version_info', (3, 12, 9))
    monkeypatch.setattr(bootstrap.platform, 'machine', lambda: 'AMD64')
    cache, model, cv = tmp_path/'models', tmp_path/'model/python.exe', tmp_path/'cv/python.exe'
    cache.mkdir()
    for p in (model, cv):
        p.parent.mkdir()
        p.write_bytes(b'synthetic executable never run')
    for key, value in [('WECFU_MODEL_HOME',cache),('WECFU_MODEL_PYTHON',model),('WECFU_CV_PYTHON',cv)]:
        monkeypatch.setenv(key,str(value))
    monkeypatch.setenv('WECFU_SAM_DEVICE','cpu')
    monkeypatch.delenv('WECFU_ENABLE_SAM2',raising=False)
    monkeypatch.setattr(runtime_paths,'MODEL_HOME',cache)
    monkeypatch.setattr(runtime_paths,'MODEL_PYTHON',Path('unchanged-model'))
    monkeypatch.setattr(runtime_paths,'CV_PYTHON',Path('unchanged-cv'))
    monkeypatch.setattr(runtime_paths,'SAM_DEVICE','cpu')
    events=[]
    def forbidden(*a,**k):
        raise AssertionError('bundled desktop must not install/write/lock')
    monkeypatch.setattr(setup_models,'setup',forbidden)
    monkeypatch.setattr(bootstrap,'_setup_lock',forbidden)
    monkeypatch.setattr(bootstrap.venv,'EnvBuilder',forbidden)
    monkeypatch.setattr(bootstrap,'_run',forbidden)
    monkeypatch.setattr(setup_models,'check',lambda path: events.append(('assets',path)))
    def probe(python,cache,*,env):
        events.append(('probe',python))
        return {'device':'cpu','versions':{}}
    monkeypatch.setattr(bootstrap,'_probe',probe)
    return cache,model,cv,events


@pytest.mark.parametrize('platform',['darwin','linux','win32'])
def test_desktop_verified_ready_without_install_lock_or_receipt(monkeypatch,bundle,platform):
    cache,model,cv,events=bundle
    monkeypatch.setattr(bootstrap.sys,'platform',platform)
    result=bootstrap.ensure_ultra()
    assert result['desktop_managed'] is True and result['installation_performed'] is False
    assert events==[('assets',cache),('probe',model),('probe',cv)]
    assert runtime_paths.MODEL_PYTHON==model and runtime_paths.CV_PYTHON==cv
    assert list(cache.iterdir())==[]


@pytest.mark.parametrize('bad',['missing-model','relative-assets','linked-model','bad-assets','bad-cv'])
def test_desktop_failure_never_falls_back_or_partially_activates(monkeypatch,bundle,bad):
    cache,model,cv,events=bundle
    if bad=='missing-model':model.unlink()
    elif bad=='relative-assets':monkeypatch.setenv('WECFU_MODEL_HOME','relative/cache')
    elif bad=='linked-model':
        model.unlink();model.symlink_to(cv)
    elif bad=='bad-assets':
        monkeypatch.setattr(setup_models,'check',lambda *a: (_ for _ in ()).throw(RuntimeError('bad assets')))
    else:
        def probe(python,cache,*,env):
            if python==cv:raise RuntimeError('bad CV')
            return {'device':'cpu'}
        monkeypatch.setattr(bootstrap,'_probe',probe)
    with pytest.raises(RuntimeError):bootstrap.ensure_ultra()
    assert runtime_paths.MODEL_PYTHON==Path('unchanged-model')
    assert list(cache.iterdir())==[]


def test_windows_cpu_x64_required_before_any_asset_read(monkeypatch,bundle):
    monkeypatch.setattr(bootstrap.sys,'platform','win32')
    monkeypatch.setenv('WECFU_SAM_DEVICE','mps')
    with pytest.raises(RuntimeError,match='x64 CPU'):bootstrap.ensure_ultra()
    monkeypatch.setenv('WECFU_SAM_DEVICE','cpu')
    monkeypatch.setattr(bootstrap.platform,'machine',lambda:'ARM64')
    with pytest.raises(RuntimeError,match='x64 CPU'):bootstrap.ensure_ultra()
    assert bundle[3]==[]


def test_windows_prepared_interpreter_uses_scripts_not_bin(monkeypatch,tmp_path):
    monkeypatch.setattr(bootstrap.sys,'platform','win32')
    monkeypatch.setattr(bootstrap.platform,'machine',lambda:'AMD64')
    folder=bootstrap.runtime_directory(tmp_path)
    (folder/'Scripts').mkdir(parents=True)
    (folder/'Scripts/python.exe').write_bytes(b'placeholder')
    (folder/'verified-runtime.json').write_text(json.dumps({'runtime_id':bootstrap.RUNTIME_ID}))
    assert bootstrap.prepared_python(tmp_path)==folder/'Scripts/python.exe'


def test_windows_asset_publish_is_verified_and_never_replaces_existing(monkeypatch,tmp_path):
    monkeypatch.setattr(setup_models.sys,'platform','win32')
    # Simulate the documented Windows rename non-overwrite behavior on POSIX.
    calls=[]
    def windows_rename(source,dest):
        calls.append((Path(source).read_bytes(),dest))
        with Path(dest).open('xb') as out:out.write(Path(source).read_bytes())
        Path(source).unlink()
    monkeypatch.setattr(setup_models.os,'rename',windows_rename)
    dest=tmp_path/'asset';data=b'known pinned bytes';sha=hashlib.sha256(data).hexdigest()
    setup_models._copy_verified(io.BytesIO(data),dest,sha,len(data))
    assert dest.read_bytes()==data and len(calls)==1
    setup_models._copy_verified(io.BytesIO(b'ignored'),dest,sha,len(data))
    assert len(calls)==1
    with pytest.raises(RuntimeError,match='not overwritten'):
        setup_models._copy_verified(io.BytesIO(b'bad'),dest,'0'*64,3)
    with pytest.raises(RuntimeError,match='digest or size'):
        setup_models._copy_verified(io.BytesIO(b'bad'),tmp_path/'wrong',sha,len(data))
    assert not (tmp_path/'wrong').exists() and not list(tmp_path.glob('.asset-*'))


def test_asset_concurrent_publication_is_not_overwritten(monkeypatch,tmp_path):
    monkeypatch.setattr(setup_models.sys,'platform','win32')
    dest=tmp_path/'asset'
    def race(source,target):
        dest.write_bytes(b'other writer')
        raise FileExistsError('synthetic concurrent destination')
    monkeypatch.setattr(setup_models.os,'rename',race)
    with pytest.raises(FileExistsError):
        setup_models._copy_verified(io.BytesIO(b'x'),dest,hashlib.sha256(b'x').hexdigest(),1)
    assert dest.read_bytes()==b'other writer' and not list(tmp_path.glob('.asset-*'))


def test_windows_sam_capability_rejects_non_cpu_before_probe(monkeypatch):
    from wecfu.server import sam_runtime
    monkeypatch.setattr(sam_runtime.sys,'platform','win32')
    monkeypatch.setattr(platform_runtime,'platform_machine',lambda:'AMD64')
    monkeypatch.setattr(sam_runtime,'SAM_DEVICE','mps')
    with pytest.raises(sam_runtime.RuntimeUnavailable,match='x64 CPU'):
        sam_runtime.LocalSamProvider().require_available()
    monkeypatch.setattr(runtime_paths,'SAM_DEVICE','mps')
    with pytest.raises(RuntimeError,match='x64 CPU'):
        setup_models.runtime_check(Path('not read'),profile='sam')
