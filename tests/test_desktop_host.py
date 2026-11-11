"""Desktop admission and actual socket/control lifecycle, using synthetic data."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import socket
from types import SimpleNamespace
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from wecfu.desktop_host import COOKIE, DesktopSessionGuard, resource_path, watch_control

SID = 'a' * 32


@pytest.fixture
def client():
    app = FastAPI()
    @app.get('/')
    async def root():
        return {'ok': True}
    @app.api_route('/api/probe', methods=['GET', 'POST', 'DELETE'])
    async def probe():
        return {'ok': True}
    return TestClient(DesktopSessionGuard(app, port=43210, session_id=SID),
                      base_url='http://127.0.0.1:43210')


def test_cookie_handshake_and_origin_checked_before_mutation(client):
    assert client.get('/api/probe').status_code == 403
    assert client.get('/?desktop_session=' + 'b' * 32).status_code == 403
    result = client.get('/?desktop_session=' + SID)
    assert result.status_code == 200
    assert 'HttpOnly' in result.headers['set-cookie']
    assert 'SameSite=Strict' in result.headers['set-cookie']
    assert result.headers['referrer-policy'] == 'no-referrer'
    assert client.get('/api/probe').status_code == 200
    assert client.post('/api/probe').status_code == 403
    assert client.post('/api/probe', headers={'origin': 'http://127.0.0.1:43210'}).status_code == 200
    for origin in ('https://unrelated.example', 'null', 'http://localhost:43210', 'http://127.0.0.1:1234'):
        assert client.post('/api/probe', headers={'origin': origin}).status_code == 403
    assert client.get('/api/probe', headers={'Host': 'unrelated.example:43210'}).status_code == 403


def test_cross_origin_bootstrap_and_duplicate_query_do_not_mint_cookie(client):
    for query in ('?desktop_session=' + SID + '&desktop_session=' + SID, '?desktop_session=wrong'):
        assert 'set-cookie' not in client.get('/' + query).headers
    assert client.get('/?desktop_session=' + SID, headers={'origin': 'https://unrelated.example'}).status_code == 403


@pytest.mark.parametrize('value', ['broken', '"\\377"', '', 'a' * 129])
def test_malformed_cookie_fails_closed_without_server_error(client, value):
    assert client.get('/api/probe', headers={'cookie': COOKIE + '=' + value}).status_code == 403


@pytest.mark.parametrize('value', ['../escape', '/etc/a', 'C:/a', 'a\\b', 'a//b', './a', 'a/../b',
                                  'a/./b', 'a/NUL.txt', 'CON', 'a.', 'a ', 'a\x00b', 'a\nb'])
def test_portable_paths_reject_unsafe_forms(tmp_path, value):
    with pytest.raises(ValueError):
        resource_path(tmp_path, value)


def test_portable_paths_allow_unicode_spaces_and_reject_escaping_symlink(tmp_path):
    assert resource_path(tmp_path, '照片 文件/app.txt') == tmp_path / '照片 文件/app.txt'
    outside = tmp_path.parent / (tmp_path.name + '-outside')
    outside.mkdir()
    try:
        (tmp_path / 'escape').symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip('Account cannot create symbolic links')
    with pytest.raises(ValueError):
        resource_path(tmp_path, 'escape/file.txt')


@pytest.mark.parametrize('data', [b'', b'broken\n', b'x' * 4097, b'{}\n',
    json.dumps({'command': 'shutdown', 'session_id': SID}).encode() + b'\n'])
def test_control_eof_shutdown_and_bad_protocol_stop_service(data):
    server = SimpleNamespace(should_exit=False)
    watch_control(server, SID, io.BytesIO(data), threading.Event())
    assert server.should_exit


@pytest.mark.parametrize('shutdown', ['command', 'eof'])
def test_actual_loopback_launch_cookie_control_and_session_cleanup(shutdown):
    code = '''
from fastapi import FastAPI
from types import SimpleNamespace
from wecfu.desktop_host import run_service
def factory(get_root, web_mode):
 app=FastAPI()
 app.state.model_preview_manager=SimpleNamespace(sam=SimpleNamespace(require_available=lambda: None))
 @app.get('/')
 async def root(): return {'root':str(get_root())}
 return app
run_service(session_id='aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', version='synthetic', app_factory=factory)
'''
    process = subprocess.Popen([sys.executable, '-B', '-c', code], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               env={**os.environ, 'PYTHONPATH': str(Path(__file__).parents[1])})
    try:
        result = []
        reader = threading.Thread(target=lambda: result.append(process.stdout.readline()), daemon=True)
        reader.start(); reader.join(10)
        assert result, 'service never became ready'
        ready = json.loads(result[0])
        assert ready['event'] == 'ready' and ready['version'] == 'synthetic'
        parsed = urlsplit(ready['url'])
        assert parsed.hostname == '127.0.0.1' and parsed.port != 8765
        with urlopen(ready['url'], timeout=3) as response:
            root = Path(json.load(response)['root'])
            assert root.exists()
        if shutdown == 'command':
            process.stdin.write(json.dumps({'command': 'shutdown', 'session_id': SID}).encode() + b'\n')
            process.stdin.flush()
        else:
            process.stdin.close()
        assert process.wait(timeout=10) == 0
        assert not root.exists()
        assert b'Traceback' not in process.stderr.read()
    finally:
        if process.poll() is None:
            process.kill(); process.wait(timeout=4)


@pytest.mark.parametrize('fail', [False, True])
def test_actual_listener_waits_for_provider_and_config_uses_verified_instance(tmp_path, fail):
    """Actual sockets and actual config route, with an explicitly fake slow provider."""
    code = r'''
import json, os, socket, sys, time
from pathlib import Path
from wecfu.desktop_host import run_service
from wecfu.server.app import build_app
from wecfu import runtime_bootstrap
folder=Path(sys.argv[1]); fail=sys.argv[2]=='fail'
def forbidden(*args, **kwargs):
 raise AssertionError('Synthetic startup test must not run model/runtime subprocesses')
runtime_bootstrap._probe=forbidden
original_socket=socket.socket
class ObservedSocket(original_socket):
 def bind(self, address):
  result=super().bind(address)
  if address==('127.0.0.1', 0):
   (folder/'bound.json').write_text(json.dumps(self.getsockname()))
  return result
socket.socket=ObservedSocket
class SyntheticProvider:
 def __init__(self):
  self.verified=False; self.cold_checks=0; self.calls=0
 def require_available(self):
  self.calls+=1
  if self.verified: return
  self.cold_checks+=1
  (folder/'checking').write_text('synthetic capability check in progress')
  deadline=time.monotonic()+15
  while not (folder/'release').exists():
   if time.monotonic()>deadline: raise RuntimeError('Synthetic check was not released')
   time.sleep(.02)
  if fail: raise RuntimeError('Synthetic provider verification failed')
  self.verified=True
 def capability(self):
  self.require_available()
  return {'available':self.verified,'cold_checks':self.cold_checks,'calls':self.calls}
def factory(get_root, web_mode):
 app=build_app(get_root=get_root, web_mode=web_mode)
 app.state.model_preview_manager.sam=SyntheticProvider()
 (folder/'workspace').write_text(str(get_root()))
 return app
try:
 run_service(session_id='aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', version='synthetic', app_factory=factory)
except RuntimeError as error:
 if str(error)!='Synthetic provider verification failed': raise
 raise SystemExit(17)
'''
    process = subprocess.Popen([sys.executable, '-B', '-c', code, str(tmp_path), 'fail' if fail else 'pass'],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               env={**os.environ, 'PYTHONPATH': str(Path(__file__).parents[1]),
                                    'WECFU_ENABLE_FUSION_V2': '0'})
    messages = []
    reader = threading.Thread(target=lambda: messages.append(process.stdout.readline()), daemon=True)
    reader.start()
    try:
        deadline = time.monotonic() + 30
        while not (tmp_path / 'checking').exists() and time.monotonic() < deadline:
            assert process.poll() is None, 'synthetic service exited before preflight'
            time.sleep(.02)
        assert (tmp_path / 'checking').exists(), 'synthetic preflight did not start'
        address = tuple(json.loads((tmp_path / 'bound.json').read_text()))
        workspace = Path((tmp_path / 'workspace').read_text())
        assert workspace.exists()
        for _ in range(3):
            with pytest.raises(OSError):
                socket.create_connection(address, timeout=.2)
        assert not messages, 'ready was emitted before capability verification'
        (tmp_path / 'release').write_text('continue synthetic capability check')
        if fail:
            assert process.wait(timeout=10) == 17
            reader.join(2)
            assert messages == [b''], 'failed preflight emitted a ready message'
            with pytest.raises(OSError):
                socket.create_connection(address, timeout=.2)
        else:
            reader.join(10)
            assert messages, 'verified service never became ready'
            ready = json.loads(messages[0])
            assert ready['event'] == 'ready'
            parsed = urlsplit(ready['url'])
            assert (parsed.hostname, parsed.port) == address
            with urlopen(ready['url'], timeout=3) as response:
                assert response.status == 200
            request = Request(f'http://{address[0]}:{address[1]}/api/config',
                              headers={'Cookie': f'{COOKIE}={SID}'})
            with urlopen(request, timeout=3) as response:
                capability = json.load(response)['models']['sam2']
            assert capability['available'] is True
            assert capability['cold_checks'] == 1 and capability['calls'] == 2
            process.stdin.write(json.dumps({'command': 'shutdown', 'session_id': SID}).encode() + b'\n')
            process.stdin.flush()
            assert process.wait(timeout=10) == 0
        assert not workspace.exists()
        assert b'Traceback' not in process.stderr.read()
    finally:
        if process.poll() is None:
            process.kill(); process.wait(timeout=4)
        reader.join(2)


def test_app_factory_without_capability_contract_cannot_skip_preflight(tmp_path, monkeypatch):
    from wecfu.desktop_host import run_service
    events = []
    monkeypatch.setattr('wecfu.desktop_host.emit', lambda event: events.append(event))
    with pytest.raises(AttributeError):
        run_service(session_id=SID, version='synthetic', app_factory=lambda **kwargs: FastAPI())
    assert events == []


def test_shell_owned_workspace_is_retained_for_shell_cleanup(tmp_path):
    from wecfu.desktop_host import workspace_directory
    owned = tmp_path / 'new-session'
    owned.mkdir()
    with workspace_directory(owned) as root:
        assert root == owned.resolve()
        (root / 'synthetic-input').write_text('owned by the native session')
    assert (owned / 'synthetic-input').is_file()
    with pytest.raises(RuntimeError, match='new empty owned directory'):
        with workspace_directory(owned):
            pytest.fail('Existing session data was accepted')
    assert (owned / 'synthetic-input').read_text() == 'owned by the native session'


def test_workspace_rejects_missing_relative_or_linked_directory(tmp_path):
    from wecfu.desktop_host import workspace_directory
    for path in (tmp_path / 'missing', Path('relative-session')):
        with pytest.raises(RuntimeError, match='new empty owned directory'):
            with workspace_directory(path):
                pytest.fail('Invalid session directory accepted')
    owned = tmp_path / 'owned'
    owned.mkdir()
    link = tmp_path / 'link'
    try:
        link.symlink_to(owned, target_is_directory=True)
    except OSError:
        pytest.skip('Account cannot create symbolic links')
    with pytest.raises(RuntimeError, match='new empty owned directory'):
        with workspace_directory(link):
            pytest.fail('Linked session directory accepted')


def test_workspace_rejects_windows_junction(tmp_path, monkeypatch):
    from wecfu.desktop_host import workspace_directory
    monkeypatch.setattr(Path, 'is_junction', lambda self: True, raising=False)
    with pytest.raises(RuntimeError, match='new empty owned directory'):
        with workspace_directory(tmp_path):
            pytest.fail('Junction accepted')
