"""Synthetic metadata/HTTP/ownership checks; never launch a GUI or model here."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import time
from types import SimpleNamespace

import pytest

from tools import windows_shell_smoke as smoke


TOKEN = 'a' * 32


def fixture(tmp_path):
    installed = tmp_path/'安装 WeCFU'/'wecfu-desktop.exe'
    installed.parent.mkdir(); installed.write_bytes(b'fixed synthetic EXE')
    bundle = installed.parent/'bundle'; bundle.mkdir()
    manifest = {'python': 'runtime/python.exe', 'entrypoint': 'app/desktop_entry.py', 'app_version': 'synthetic'}
    (bundle/'bundle-manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    temp = tmp_path/'test-temp'; temp.mkdir()
    workspace = temp/('wecfu-desktop-session-' + 'b'*32); workspace.mkdir()
    moment = int(time.time()*1000)
    args = [str(bundle/'runtime/python.exe'), '-I', '-B', str(bundle/'app/desktop_entry.py'),
            '--resource-root', str(bundle), '--session-id', TOKEN, '--workspace-root', str(workspace)]
    data = {'shell': {'pid': 20, 'parent': 10, 'executable': str(installed), 'created_ms': moment},
            'children': [{'pid': 30, 'parent': 20, 'executable': args[0], 'created_ms': moment, 'command': json.dumps(args)}],
            'listeners': [{'pid': 30, 'address': '127.0.0.1', 'port': 54321}]}
    kwargs = dict(shell_pid=20, owner_pid=10, installed=installed, bundle=bundle, manifest=manifest,
                  temp_root=temp, launched_ms=moment, parse=json.loads)
    return data, kwargs, args


def test_exact_owned_runtime_unicode_paths_and_capability_remain_separate(tmp_path):
    data, kwargs, args = fixture(tmp_path)
    result = smoke.validate_snapshot(data, **kwargs)
    assert result['session'] == TOKEN and result['origin'] == 'http://127.0.0.1:54321'
    assert TOKEN not in json.dumps(result['identity'])
    assert result['identity']['runtime'] == args[0]
    assert smoke.validate_snapshot(data, **kwargs, expected_identity=result['identity']) == result


@pytest.mark.parametrize('mutation', ['shell_parent', 'shell_exe', 'old_shell', 'host_parent', 'host_exe',
    'old_child', 'other_listener', 'public_listener', 'duplicate_listener', 'bad_port', 'multiple_hosts',
    'runtime_arg', 'entry_arg', 'root_arg', 'session_arg', 'workspace_arg', 'extra_arg'])
def test_unowned_mismatched_and_nonprivate_runtime_metadata_is_rejected(tmp_path, mutation):
    data, kwargs, args = fixture(tmp_path)
    if mutation == 'shell_parent': data['shell']['parent'] = 999
    if mutation == 'shell_exe': data['shell']['executable'] += '.other'
    if mutation == 'old_shell': data['shell']['created_ms'] -= 10000
    if mutation == 'host_parent': data['children'][0]['parent'] = 999
    if mutation == 'host_exe': data['children'][0]['executable'] += '.other'
    if mutation == 'old_child': data['children'][0]['created_ms'] -= 10000
    if mutation == 'other_listener': data['listeners'][0]['pid'] = 999
    if mutation == 'public_listener': data['listeners'][0]['address'] = '0.0.0.0'
    if mutation == 'duplicate_listener': data['listeners'] *= 2
    if mutation == 'bad_port': data['listeners'][0]['port'] = True
    if mutation == 'multiple_hosts': data['children'] *= 2
    if mutation == 'runtime_arg': args[0] += '.other'
    if mutation == 'entry_arg': args[3] += '.other'
    if mutation == 'root_arg': args[5] += '-other'
    if mutation == 'session_arg': args[7] = 'not-a-session'
    if mutation == 'workspace_arg': args[9] = str(tmp_path/'unowned-workspace')
    if mutation == 'extra_arg': args += ['--unexpected']
    data['children'][0]['command'] = json.dumps(args)
    with pytest.raises(smoke.SmokeFailure): smoke.validate_snapshot(data, **kwargs)


def test_readiness_waits_but_identity_changes_or_disappearance_after_ready_fail(tmp_path):
    data, kwargs, _ = fixture(tmp_path)
    identity = smoke.validate_snapshot(data, **kwargs)['identity']
    waiting = deepcopy(data); waiting['listeners'] = []
    assert smoke.validate_snapshot(waiting, **kwargs) is None
    with pytest.raises(smoke.SmokeFailure): smoke.validate_snapshot(waiting, **kwargs, expected_identity=identity)
    waiting['children'] = []
    assert smoke.validate_snapshot(waiting, **kwargs) is None
    with pytest.raises(smoke.SmokeFailure): smoke.validate_snapshot(waiting, **kwargs, expected_identity=identity)
    data['children'][0]['created_ms'] += 1
    with pytest.raises(smoke.SmokeFailure, match='identity changed'):
        smoke.validate_snapshot(data, **kwargs, expected_identity=identity)


class Response:
    def __init__(self, status, payload): self.status, self.payload = status, payload
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self, size): return self.payload[:size]


@pytest.mark.parametrize('mutation', ['none', 'not_empty', 'ultra_missing', 'wrong_status', 'oversize'])
def test_http_is_read_only_bounded_and_receipt_never_contains_session(tmp_path, monkeypatch, mutation):
    payloads = [Response(403, b'denied'), Response(200, b'<html>bootstrap</html>'),
                Response(200, b'{"batches":[]}'), Response(200, b'{"default_model":"sam2_local_v1","models":{"sam2":{"available":true}}}')]
    if mutation == 'not_empty': payloads[2] = Response(200, b'{"batches":["old"]}')
    if mutation == 'ultra_missing': payloads[3] = Response(200, b'{"default_model":"classic"}')
    if mutation == 'wrong_status': payloads[0] = Response(200, b'wrong')
    if mutation == 'oversize': payloads[1] = Response(200, b'x'*(smoke.MAX_RESPONSE+1))
    seen = []
    def request(req, timeout):
        assert req.get_method() == 'GET' and req.data is None and 0 < timeout <= 10
        assert req.get_header('Origin') == 'http://127.0.0.1:54321'
        seen.append(req.full_url)
        return payloads[len(seen)-1]
    monkeypatch.setattr(smoke, 'build_opener', lambda *args: SimpleNamespace(open=request))
    call = lambda: smoke.check_http({'origin':'http://127.0.0.1:54321', 'session': TOKEN}, time.monotonic()+30)
    if mutation != 'none':
        with pytest.raises(smoke.SmokeFailure): call()
    else:
        result = call()
        assert len(result) == 4 and TOKEN not in json.dumps(result)
        assert [r['check'] for r in result] == ['unauthorized_batches','session_bootstrap','empty_batches','ultra_available']
        assert all('/model' not in url for url in seen)


def test_redirects_are_never_followed():
    with pytest.raises(smoke.SmokeFailure, match='redirected'):
        smoke.NoRedirect().redirect_request(None, None, None, None, None, 'https://example.com/')


@pytest.mark.parametrize('failure', ['none', 'secret_exception', 'expired_deadline', 'cleanup', 'changed_exe'])
def test_run_owns_shell_and_always_retires_job_with_redacted_evidence(tmp_path, monkeypatch, failure):
    from wecfu import platform_runtime
    data, kwargs, args = fixture(tmp_path)
    output = tmp_path/'evidence'
    expected = smoke.sha(kwargs['installed'])
    events = []
    class Process:
        pid = 10
        stdin = SimpleNamespace(close=lambda: events.append('stdin_closed'))
        def poll(self): return None
    process = Process()
    def spawn(command, **options):
        assert command[1] == '-B' and command[3] == str(kwargs['installed'])
        assert options['stdout'] == options['stderr'] == subprocess.DEVNULL
        assert not any(k.startswith('WECFU_') for k in options['env'])
        assert options['env']['TMP'] == str(output/'session-temp')
        Path(command[4]).write_text('{"pid":20}', encoding='utf-8')
        events.append('spawn_owned')
        return process
    def metadata(*unused):
        if failure == 'secret_exception':
            raise RuntimeError('private URL ?desktop_session=' + TOKEN)
        if failure == 'expired_deadline':
            raise smoke.SmokeFailure('Installed shell smoke exceeded its bounded deadline')
        args[9] = str(output/'session-temp'/('wecfu-desktop-session-'+'b'*32))
        data['children'][0]['command'] = json.dumps(args)
        return data
    validate = smoke.validate_snapshot
    monkeypatch.setattr(smoke, 'validate_snapshot', lambda data, **kw: validate(data, **kw, parse=json.loads))
    monkeypatch.setattr(smoke.sys, 'platform', 'win32')
    monkeypatch.setattr(platform_runtime, 'spawn_owned', spawn)
    def stop(p, timeout):
        assert p is process and timeout == 5
        events.append('stop_owned')
        if failure == 'cleanup': raise RuntimeError('private ' + TOKEN)
    monkeypatch.setattr(platform_runtime, 'stop_owned', stop)
    monkeypatch.setattr(smoke, 'read_metadata', metadata)
    def http(capability, deadline):
        if failure == 'changed_exe': kwargs['installed'].write_bytes(b'changed after launch')
        return [{'check': 'synthetic-read-only'}]
    monkeypatch.setattr(smoke, 'check_http', http)
    call = lambda: smoke.run(kwargs['installed'], kwargs['bundle'], kwargs['manifest'], output, expected, time.monotonic()+180)
    if failure == 'none':
        result = call()
        assert result['model_requests'] == 0 and result['sha256'] == smoke.sha(output/'result.json')
    else:
        with pytest.raises(smoke.SmokeFailure): call()
    assert events == ['spawn_owned','stdin_closed','stop_owned']
    receipt_raw = (output/'result.json').read_text(encoding='utf-8')
    assert TOKEN not in receipt_raw and '?desktop_session' not in receipt_raw
    receipt = json.loads(receipt_raw)
    assert receipt['status'] == ('passed' if failure == 'none' else 'failed')
    assert receipt['model_requests'] == 0 and receipt['ui_automation'] is False and receipt['graceful_close_tested'] is False
    if failure != 'cleanup': assert receipt['forced_job_cleanup']['all_owned_processes_retired'] is True


def test_nonwindows_and_wrong_exe_refuse_before_any_spawn(tmp_path, monkeypatch):
    from wecfu import platform_runtime
    _, kwargs, _ = fixture(tmp_path)
    monkeypatch.setattr(platform_runtime, 'spawn_owned', lambda *a, **k: pytest.fail('Must not spawn'))
    monkeypatch.setattr(smoke.sys, 'platform', 'darwin')
    with pytest.raises(smoke.SmokeFailure):
        smoke.run(kwargs['installed'], kwargs['bundle'], kwargs['manifest'], tmp_path/'not-windows', smoke.sha(kwargs['installed']), time.monotonic()+180)
    monkeypatch.setattr(smoke.sys, 'platform', 'win32')
    with pytest.raises(smoke.SmokeFailure):
        smoke.run(kwargs['installed'], kwargs['bundle'], kwargs['manifest'], tmp_path/'wrong-exe', '0'*64, time.monotonic()+180)


def test_metadata_script_is_read_only_and_no_ui_or_remote_apis_are_used():
    assert 'Get-CimInstance Win32_Process' in smoke.METADATA
    assert 'Get-NetTCPConnection -OwningProcess' in smoke.METADATA
    for forbidden in ('SendKeys', 'SendMessage', 'PostMessage', 'WM_CLOSE', 'Invoke-Command', '-ComputerName', 'WinAppDriver'):
        assert forbidden not in smoke.METADATA + smoke.WRAPPER
    assert 'subprocess.DEVNULL' in smoke.WRAPPER and 'child.wait()' in smoke.WRAPPER
