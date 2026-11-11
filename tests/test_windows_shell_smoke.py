"""Synthetic metadata/HTTP/ownership checks; never launch a GUI or model here."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
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
    for name in (manifest['python'], manifest['entrypoint']):
        target = bundle/name; target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b'synthetic existing resource')
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


def test_path_identity_requires_existing_same_file_or_directory(tmp_path):
    first = tmp_path/'first'; first.write_bytes(b'identical bytes')
    second = tmp_path/'second'; second.write_bytes(b'identical bytes')
    missing = tmp_path/'missing'
    assert smoke.same_path(str(first), first)
    assert smoke.same_path(str(tmp_path), tmp_path)
    assert not smoke.same_path(str(first), second)
    assert not smoke.same_path(str(missing), missing)
    assert not smoke.same_path(str(first), missing)
    assert not smoke.same_path(str(missing), first)
    assert not smoke.same_path('', first)


@pytest.mark.skipif(sys.platform != 'win32', reason='Requires real Windows extended-path filesystem identity')
def test_windows_extended_and_ordinary_paths_identify_the_same_existing_runtime(tmp_path):
    data, kwargs, args = fixture(tmp_path)
    def extended(path):
        normal = str(path)
        assert not normal.startswith('\\\\?\\')
        return '\\\\?\\' + normal
    first = kwargs['bundle']/kwargs['manifest']['python']
    other = kwargs['bundle']/kwargs['manifest']['entrypoint']
    assert smoke.same_path(extended(first), first)
    assert smoke.same_path(str(first), Path(extended(first)))
    assert not smoke.same_path(extended(first), other)
    assert not smoke.same_path(extended(first.parent/'missing.exe'), first)
    data['shell']['executable'] = extended(kwargs['installed'])
    data['children'][0]['executable'] = extended(first)
    for index in (0, 3, 5, 9):
        args[index] = extended(args[index])
    data['children'][0]['command'] = json.dumps(args)
    result = smoke.validate_snapshot(data, **kwargs)
    assert result['session'] == TOKEN and result['identity']['runtime'] == str(first)


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


@pytest.mark.parametrize('outcome', ['success', 'timeout', 'invalid_json', 'nonzero'])
def test_metadata_diagnostics_keep_only_fixed_phases_and_never_raw_capabilities(tmp_path, monkeypatch, outcome):
    monkeypatch.setenv('SystemRoot', str(tmp_path/'Windows'))
    stderr = ('raw private ?desktop_session=' + TOKEN + '\n'
              'WECFU_METADATA_PHASE script_started 0\n'
              'WECFU_METADATA_PHASE shell_query_started 2\n'
              'WECFU_METADATA_PHASE not_allowed 3\n'
              'WECFU_METADATA_PHASE completed 999999\n').encode()
    captured = []
    def execute(command, **kwargs):
        captured.append(kwargs['timeout'])
        assert command[-2:] == ['20', '10'] and '-NonInteractive' in command
        assert kwargs['capture_output'] is True and kwargs['check'] is False
        if outcome == 'timeout':
            raise subprocess.TimeoutExpired(command, kwargs['timeout'], output=TOKEN.encode(), stderr=stderr)
        return SimpleNamespace(returncode=1 if outcome == 'nonzero' else 0, stderr=stderr,
                               stdout=b'not-json '+TOKEN.encode() if outcome == 'invalid_json' else json.dumps({'secret':TOKEN}).encode())
    monkeypatch.setattr(smoke.subprocess, 'run', execute)
    diagnostics = []
    call = lambda: smoke.read_metadata(tmp_path/'query.ps1', 20, 10, time.monotonic()+2, diagnostics=diagnostics)
    if outcome == 'success':
        assert call() == {'secret': TOKEN}
    else:
        with pytest.raises(smoke.SmokeFailure) as failure: call()
        assert TOKEN not in str(failure.value)
        if outcome == 'timeout': assert 'shell_query_started' in str(failure.value)
    assert 0 < captured[0] <= 2 < smoke.METADATA_QUERY_SECONDS
    assert TOKEN not in json.dumps(diagnostics)
    assert diagnostics[0]['phases'] == [{'phase':'script_started', 'elapsed_ms':0}, {'phase':'shell_query_started', 'elapsed_ms':2}]
    assert diagnostics[0]['seconds'] >= 0
    assert diagnostics[0]['status'] == {'success':'completed','timeout':'timeout','invalid_json':'invalid_response','nonzero':'process_returned'}[outcome]


def test_metadata_timeout_before_script_start_has_safe_specific_phase(tmp_path, monkeypatch):
    monkeypatch.setenv('SystemRoot', str(tmp_path/'Windows'))
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired('sensitive '+TOKEN, kwargs['timeout'], stderr=TOKEN.encode())
    monkeypatch.setattr(smoke.subprocess, 'run', timeout)
    diagnostics = []
    with pytest.raises(smoke.SmokeFailure, match='powershell_startup'):
        smoke.read_metadata(tmp_path/'query.ps1', 20, 10, time.monotonic()+120, diagnostics=diagnostics)
    assert diagnostics[0]['timeout_seconds'] == 45 and diagnostics[0]['phases'] == []
    assert TOKEN not in json.dumps(diagnostics)


@pytest.mark.skipif(sys.platform != 'win32', reason='Exercises actual local Windows CIM/TCP metadata with owned synthetic processes')
def test_windows_native_metadata_on_owned_dummy_host_and_loopback_socket(tmp_path, record_property):
    """Cold metadata integration gate; no installer, GUI, model or user files."""
    from wecfu.platform_runtime import spawn_owned, stop_owned
    deadline = time.monotonic() + smoke.START_SECONDS
    bundle = tmp_path/'synthetic bundle'; bundle.mkdir()
    temp_root = tmp_path/'session-temp'; temp_root.mkdir()
    workspace = temp_root/('wecfu-desktop-session-'+'c'*32); workspace.mkdir()
    host = bundle/'entry.py'
    host.write_text('''import argparse,json,socket,time
from pathlib import Path
parser=argparse.ArgumentParser()
parser.add_argument('--resource-root');parser.add_argument('--session-id');parser.add_argument('--workspace-root')
args=parser.parse_args()
with socket.socket() as listener:
 listener.bind(('127.0.0.1',0));listener.listen(1)
 Path(args.resource_root,'host-ready.json').write_text(json.dumps({'port':listener.getsockname()[1]}),encoding='utf-8')
 time.sleep(120)
''', encoding='utf-8')
    shell = tmp_path/'dummy-shell.py'
    shell.write_text('''import subprocess,sys
child=subprocess.Popen([sys.executable,'-I','-B',sys.argv[1],'--resource-root',sys.argv[2],'--session-id',sys.argv[3],'--workspace-root',sys.argv[4]],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
raise SystemExit(child.wait())
''', encoding='utf-8')
    owner = tmp_path/'dummy-owner.py'
    owner.write_text('''import json,subprocess,sys
from pathlib import Path
child=subprocess.Popen([sys.executable,'-B',*sys.argv[1:6]],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
Path(sys.argv[6]).write_text(json.dumps({'pid':child.pid}),encoding='utf-8')
raise SystemExit(child.wait())
''', encoding='utf-8')
    script = tmp_path/'metadata.ps1'; script.write_text(smoke.METADATA, encoding='utf-8-sig')
    launch = tmp_path/'launch.json'
    diagnostics = []; retired = False; process = None
    try:
        launched_ms = int(time.time()*1000)
        process = spawn_owned([sys.executable, '-B', str(owner), str(shell), str(host), str(bundle), TOKEN,
                               str(workspace), str(launch)], cwd=tmp_path, stdin=subprocess.PIPE,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        process.stdin.close()
        ready_deadline = min(deadline - 90, time.monotonic()+20)
        ready = bundle/'host-ready.json'
        launched = listener = None
        while launched is None or listener is None:
            assert process.poll() is None, 'Synthetic owned process exited before readiness'
            if launch.is_file() and ready.is_file():
                try:
                    launched = json.loads(launch.read_text(encoding='utf-8'))
                    listener = json.loads(ready.read_text(encoding='utf-8'))
                except ValueError:
                    launched = listener = None
                if launched is not None and listener is not None:
                    break
            smoke.remaining(ready_deadline, 1)
            time.sleep(.05)
        shell_pid = launched['pid']
        # This synthetic manifest deliberately names the existing test Python;
        # it tests metadata identity, not the production manifest validator.
        manifest = {'python': sys.executable, 'entrypoint': host.name}
        snapshot = smoke.read_metadata(script, shell_pid, process.pid, deadline - 5, diagnostics=diagnostics)
        kwargs = dict(shell_pid=shell_pid, owner_pid=process.pid, installed=Path(sys.executable),
                      bundle=bundle, manifest=manifest, temp_root=temp_root, launched_ms=launched_ms)
        capability = smoke.validate_snapshot(snapshot, **kwargs)
        assert capability is not None and capability['session'] == TOKEN
        assert capability['origin'] == 'http://127.0.0.1:' + str(listener['port'])
        second = smoke.read_metadata(script, shell_pid, process.pid, deadline - 5, diagnostics=diagnostics)
        assert smoke.validate_snapshot(second, **kwargs, expected_identity=capability['identity']) == capability
        for row in diagnostics:
            assert row['status'] == 'completed'
            assert row['phases'][0]['phase'] == 'script_started'
            assert row['phases'][-1]['phase'] == 'completed'
            assert any(phase['phase'] == 'tcp_query_complete' for phase in row['phases'])
    finally:
        try:
            if process is not None:
                stop_owned(process, timeout=5)
                retired = True
        finally:
            encoded = json.dumps({'metadata_queries': diagnostics, 'forced_job_retired': retired,
                                  'ui_automation': False, 'model_requests': 0}, ensure_ascii=False)
            assert TOKEN not in encoded
            record_property('native_metadata_diagnostics', encoded)


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
    def metadata(*unused, **unused_kwargs):
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
