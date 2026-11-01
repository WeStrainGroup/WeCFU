"""Synthetic-only portable asset/runtime boundary checks."""
import hashlib
import errno
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest import mock
import pytest
from wecfu import runtime_paths
from wecfu.setup_models import _copy_verified
from wecfu.server.fusion_dino import process_monitor


def test_asset_copy_is_digest_bound_and_never_replaces_existing(tmp_path):
    p=tmp_path/'asset.bin';raw=b'official synthetic asset';h=hashlib.sha256(raw).hexdigest()
    _copy_verified(io.BytesIO(raw),p,h,len(raw))
    assert p.read_bytes()==raw
    with pytest.raises(RuntimeError):_copy_verified(io.BytesIO(b'changed'),p,'0'*64,7)
    assert p.read_bytes()==raw
    with pytest.raises(RuntimeError):_copy_verified(io.BytesIO(raw),tmp_path/'bad.bin','0'*64,len(raw))
    assert not (tmp_path/'bad.bin').exists()
    assert not list(tmp_path.glob('.asset-*'))


def test_public_resources_have_no_host_paths_or_human_records():
    root=runtime_paths.PACKAGE_ROOT
    for rel in ('model_assets.json','server/fusion_dino/loading-metadata.json','server/fusion_dino/library-pins.json','server/fusion_dino/license-provenance.json'):
        text=(root/rel).read_text()
        assert '/Users/' not in text and 'human-calibration-' not in text
        assert 'current_source' not in text and 'human_count' not in text
    manifest=runtime_paths.asset_manifest()
    assert len(manifest['assets'])==7
    assert manifest['assets'][0]['sha256']=='7402e0d864fa82708a20fbd15bc84245c2f26dff0eb43a4b5b93452deb34be69'
    assert manifest['assets'][1]['sha256']=='af2e3769e6f1512f4dabb3043b6b4a5de97935549eaa843bfa3074728ce630ea'


def test_linux_monitor_reads_only_own_child_and_kib_units():
    monitor=object.__new__(process_monitor.OwnChildRSS)
    monitor.child=mock.Mock(pid=123,returncode=None)
    with mock.patch.object(process_monitor.sys,'platform','linux'), mock.patch.object(Path,'read_text',return_value='Name: child\nVmRSS:\t4096 kB\n') as read:
        assert monitor.resident_bytes()==4096*1024
        read.assert_called_once()
    monitor.child.returncode=0
    with pytest.raises(ValueError):monitor.resident_bytes()


def test_linux_exited_child_requires_bounded_exit_confirmation():
    monitor=object.__new__(process_monitor.OwnChildRSS)
    monitor.child=mock.Mock(pid=123,returncode=None)
    for state in ('Z','X'):
        with mock.patch.object(process_monitor.sys,'platform','linux'), mock.patch.object(Path,'read_text',return_value=f'Name: child\nState:\t{state} (exited)\n'):
            with pytest.raises(OSError) as caught:monitor.resident_bytes()
            assert caught.value.errno==errno.ESRCH
            clock=lambda:0.
            result=process_monitor.resolve_exit_race(caught.value,lambda:True,1.,clock=clock,sleep=lambda _:None)
            assert result['confirmed_exit'] and result['wait4_polls']==1
    # State may still be R/S while exit_mm has released RSS. This does not
    # itself establish exit: the same-child bounded confirmation remains due.
    with mock.patch.object(process_monitor.sys,'platform','linux'), mock.patch.object(Path,'read_text',return_value='Name: child\nState:\tR (running)\n'):
        with pytest.raises(process_monitor.LinuxRSSUnavailable):monitor.resident_bytes()


def test_windows_core_imports_without_resource_and_models_fail_before_spawn():
    import builtins,types
    source=Path(process_monitor.__file__).read_text()
    module=types.ModuleType('portable_monitor_without_resource');module.__file__=process_monitor.__file__
    original=builtins.__import__
    def importer(name,*args,**kwargs):
        if name=='resource':raise ImportError('Windows has no resource module')
        return original(name,*args,**kwargs)
    with mock.patch('builtins.__import__',side_effect=importer):exec(compile(source,module.__file__,'exec'),module.__dict__)
    assert module.resource is None
    with mock.patch.object(module.sys,'platform','win32'),mock.patch.object(module.subprocess,'Popen') as spawn:
        with pytest.raises(ValueError,match='requires Darwin/Linux'):module.supervise(['never-spawn'])
        spawn.assert_not_called()
    from wecfu.server import sam_runtime
    with mock.patch.object(sam_runtime.sys,'platform','win32'):
        capability=sam_runtime.LocalSamProvider().capability()
        assert capability['available'] is False and 'macOS or Linux' in capability['reason']


def test_real_owned_child_monitor_handshake():
    code="import json,os,resource,sys;resource.setrlimit(resource.RLIMIT_CPU,(5,5));print(json.dumps({'kind':'ready','pid':os.getpid(),'cpu_limits':{'after':[5,5]}}),flush=True);assert sys.stdin.buffer.read(1)==b'G';print('synthetic-ok')"
    report,out,err=process_monitor.supervise([sys.executable,'-c',code],rss_bytes=128*1024**2,wall_seconds=10,cpu_seconds=5,output_bytes=1024**2)
    assert report['outcome']=='success',report
    assert report['work_authorized'] and b'synthetic-ok' in out
    assert report['instantaneous_RSS_hard_limit'] is False


def test_model_math_and_restricted_load_contract_are_preserved():
    root=runtime_paths.PACKAGE_ROOT/'server/fusion_dino'
    text=(root/'dino_loading.py').read_text()
    assert "weights_only=True,map_location='cpu',mmap=True" in text
    assert "load_state_dict(mapped,strict=True,assign=False)" in text
    assert 'safe_globals([argparse.Namespace])' in text
    config=json.loads((root/'runtime-contract.json').read_text())
    assert config['model_parameters']['threshold_strict_gt']==.25
    assert config['model_parameters']['resize_shortest']==800
    assert config['model_parameters']['resize_longest']==1333
