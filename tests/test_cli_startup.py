"""Actual loopback Uvicorn lifecycle; synthetic ASGI, no models or browser."""

import argparse
import asyncio
import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
import uvicorn

from wecfu import cli
from wecfu.server import app as server


@pytest.fixture
def launch(monkeypatch, tmp_path):
    roots, events = [], []
    monkeypatch.setattr(cli.tempfile, "tempdir", str(tmp_path))

    def build_app(*, get_root, web_mode):
        assert web_mode is False
        roots.append(get_root())

        async def app(scope, receive, send):
            if scope['type'] == 'lifespan':
                assert (await receive())['type'] == 'lifespan.startup'
                events.append('startup')
                await send({'type': 'lifespan.startup.complete'})
                assert (await receive())['type'] == 'lifespan.shutdown'
                events.append('shutdown')
                await send({'type': 'lifespan.shutdown.complete'})
            else:
                events.append('http')
                await send({'type': 'http.response.start', 'status': 200, 'headers': []})
                await send({'type': 'http.response.body', 'body': b'this invocation'})

        return app

    monkeypatch.setattr(server, 'build_app', build_app)
    return argparse.Namespace(root=None, port=0, open=True, model_setup=False), roots, events


def test_browser_url_is_unique_and_only_opens_after_this_server_can_respond(launch, monkeypatch):
    args, roots, events = launch
    urls = []

    async def browser(url):
        assert events[-1] == 'startup'
        urls.append(url)
        parsed = urlsplit(url)
        assert parsed.hostname == '127.0.0.1' and parsed.port != 0
        reader, writer = await asyncio.open_connection(parsed.hostname, parsed.port)
        try:
            writer.write(b'GET / HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n')
            await writer.drain()
            response = await asyncio.wait_for(reader.read(), 2)
            assert b'200 OK' in response and b'this invocation' in response
        finally:
            writer.close()
            await writer.wait_closed()

    async def main_loop(instance):
        await asyncio.wait_for(instance.browser_task, 3)
        instance.should_exit = True

    monkeypatch.setattr(cli, '_open_browser', browser)
    monkeypatch.setattr(uvicorn.Server, 'main_loop', main_loop)
    for _ in range(2):
        assert cli._cmd_serve(args) == 0
        assert not roots[-1].exists()
    assert events == ['startup', 'http', 'shutdown'] * 2
    tokens = [parse_qs(urlsplit(u).query)['launch'][0] for u in urls]
    assert len(set(tokens)) == 2 and all(len(t) == 32 for t in tokens)


def test_occupied_port_never_opens_existing_service_and_cleans_workspace(launch, monkeypatch):
    args, roots, events = launch

    async def forbidden(url):
        pytest.fail('an occupied port must never open a browser')

    monkeypatch.setattr(cli, '_open_browser', forbidden)
    with socket.socket() as occupied:
        occupied.bind(('127.0.0.1', 0))
        occupied.listen()
        occupied.settimeout(0.05)
        args.port = occupied.getsockname()[1]
        with pytest.raises(SystemExit) as exc:
            cli._cmd_serve(args)
        assert exc.value.code != 0
        # No HTTP readiness probe was sent to the unrelated listener either.
        with pytest.raises(socket.timeout):
            occupied.accept()
    assert not roots[-1].exists() and events == ['startup', 'shutdown']


def test_failed_lifespan_never_opens_browser(launch, monkeypatch):
    args, roots, _ = launch

    async def app(scope, receive, send):
        assert (await receive())['type'] == 'lifespan.startup'
        await send({'type': 'lifespan.startup.failed', 'message': 'synthetic startup failure'})

    def build_app(**kwargs):
        roots.append(kwargs['get_root']())
        return app

    async def forbidden(url):
        pytest.fail('failed app startup must not open a browser')

    monkeypatch.setattr(server, 'build_app', build_app)
    monkeypatch.setattr(cli, '_open_browser', forbidden)
    # Older Uvicorn returns normally with should_exit; newer versions exit nonzero.
    try:
        cli._cmd_serve(args)
    except SystemExit as exc:
        assert exc.code != 0
    assert not roots[-1].exists()


def test_no_open_still_binds_and_shuts_down_without_browser(launch, monkeypatch):
    args, roots, events = launch
    args.open = False

    async def forbidden(url):
        pytest.fail('--no-open must never launch a browser')

    async def main_loop(instance):
        assert instance.started and instance.browser_task is None
        assert instance.servers[0].is_serving()
        instance.should_exit = True

    monkeypatch.setattr(cli, '_open_browser', forbidden)
    monkeypatch.setattr(uvicorn.Server, 'main_loop', main_loop)
    assert cli._cmd_serve(args) == 0
    assert events == ['startup', 'shutdown'] and not roots[-1].exists()


def test_browser_exception_cannot_skip_server_lifespan_shutdown(launch, monkeypatch, capsys):
    args, roots, events = launch

    async def broken_browser(url):
        raise RuntimeError('synthetic launcher failure')

    async def main_loop(instance):
        # Let the browser task fail independently, as it can in a live server.
        await asyncio.sleep(0)
        assert instance.browser_task.done()
        instance.should_exit = True

    monkeypatch.setattr(cli, '_open_browser', broken_browser)
    monkeypatch.setattr(uvicorn.Server, 'main_loop', main_loop)
    assert cli._cmd_serve(args) == 0
    assert events == ['startup', 'shutdown'] and not roots[-1].exists()
    assert 'closing the server normally' in capsys.readouterr().err


@pytest.mark.skipif(os.name != 'posix', reason='POSIX SIGINT lifecycle integration')
def test_actual_sigint_exits_zero_without_traceback_and_cleans_workspace():
    script = r'''
import argparse, json, os, signal
from wecfu import cli
from wecfu.server import app as server
roots, events = [], []
def build_app(*, get_root, web_mode):
    roots.append(get_root())
    async def app(scope, receive, send):
        assert scope['type'] == 'lifespan'
        assert (await receive())['type'] == 'lifespan.startup'
        events.append('startup')
        await send({'type': 'lifespan.startup.complete'})
        assert (await receive())['type'] == 'lifespan.shutdown'
        events.append('shutdown')
        await send({'type': 'lifespan.shutdown.complete'})
    return app
async def stop_after_binding(url):
    assert '?launch=' in url
    events.append('bound')
    os.kill(os.getpid(), signal.SIGINT)
server.build_app = build_app
cli._open_browser = stop_after_binding
code = cli._cmd_serve(argparse.Namespace(root=None, port=0, open=True, model_setup=False))
print(json.dumps({'code': code, 'events': events, 'workspace_exists': roots[0].exists()}))
'''
    result = subprocess.run(
        [sys.executable, '-c', script], cwd=Path(cli.__file__).resolve().parents[1],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.splitlines()[-1]) == {
        'code': 0, 'events': ['startup', 'bound', 'shutdown'], 'workspace_exists': False,
    }
    assert 'Application shutdown complete' in result.stderr
    assert 'Traceback' not in result.stderr and 'KeyboardInterrupt' not in result.stderr


@pytest.mark.parametrize('cancel', [False, True])
def test_browser_launcher_is_nonblocking_bounded_and_reaped(monkeypatch, capsys, cancel):
    async def check():
        finished = asyncio.Event()

        class Process:
            returncode = None
            kills = 0
            waits = 0

            async def wait(self):
                self.waits += 1
                await finished.wait()
                return self.returncode

            def kill(self):
                self.kills += 1
                self.returncode = -9
                finished.set()

        process = Process()

        async def spawn(*argv, **kwargs):
            assert argv[:3] == (sys.executable, '-I', '-c')
            assert argv[-1] == 'http://127.0.0.1:8765/?launch=synthetic'
            assert kwargs == {'stdout': asyncio.subprocess.DEVNULL, 'stderr': asyncio.subprocess.DEVNULL}
            return process

        monkeypatch.setattr(asyncio, 'create_subprocess_exec', spawn)
        monkeypatch.setattr(cli, '_BROWSER_OPEN_TIMEOUT', 0.02)
        task = asyncio.create_task(cli._open_browser('http://127.0.0.1:8765/?launch=synthetic'))
        # The server loop remains responsive while the browser launcher is hung.
        await asyncio.sleep(0.001)
        assert process.waits == 1 and not task.done()
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            await asyncio.wait_for(task, 1)
        assert process.kills == 1 and process.waits == 2 and process.returncode == -9

    asyncio.run(check())
    assert ('Open http://' in capsys.readouterr().err) is (not cancel)
