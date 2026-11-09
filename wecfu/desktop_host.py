"""Private desktop service: offline resources, owned socket and temporary session.

The native launcher owns this process. Its stdin is the lifetime/control pipe;
stdout contains bounded protocol messages only. No installed Conda environment,
external browser, fixed port, or model download is used by this entrypoint.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hmac
from http.cookies import SimpleCookie
import json
import os
from pathlib import Path, PurePosixPath
import re
import socket
import sys
import tempfile
import threading
from urllib.parse import parse_qs

COOKIE = 'wecfu_desktop_session'
SESSION_PATTERN = re.compile(r'^[a-f0-9]{32,128}$')


def resource_path(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or '\\' in relative:
        raise ValueError('Invalid desktop resource path')
    parts = PurePosixPath(relative)
    reserved = {'CON', 'PRN', 'AUX', 'NUL', *('COM' + str(i) for i in range(1, 10)), *('LPT' + str(i) for i in range(1, 10))}
    if (parts.is_absolute() or ':' in relative or any(ord(c) < 32 or ord(c) == 127 for c in relative)
            or any(p in ('..', '.', '') or p.endswith((' ', '.')) or p.split('.')[0].upper() in reserved
                   for p in relative.split('/'))):
        raise ValueError('Invalid desktop resource path')
    path = root.joinpath(*parts.parts)
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('Desktop resource escapes its installation')
    return path


def configure_bundle(root: Path) -> dict:
    """Verify the package contract and use only its explicit interpreter/assets."""
    manifest = json.loads((root / 'bundle-manifest.json').read_text(encoding='utf-8'))
    if manifest.get('schema_version') != 1:
        raise RuntimeError('Unsupported desktop resource manifest')
    import platform
    machine = platform.machine().lower()
    architecture = 'arm64' if machine in ('arm64', 'aarch64') else 'x64' if machine in ('amd64', 'x86_64') else machine
    if manifest.get('platform') != f'{sys.platform}-{architecture}':
        raise RuntimeError('This desktop package does not match this computer')
    python = resource_path(root, manifest['python'])
    if not python.is_file() or not python.samefile(sys.executable):
        raise RuntimeError('Desktop must use its bundled Python interpreter')
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError('Desktop requires its bundled Python 3.12')
    if not isinstance(manifest.get('app_version'), str) or not manifest['app_version']:
        raise RuntimeError('Desktop version is missing')
    assets = resource_path(root, manifest.get('models', 'models'))
    os.environ.update(WECFU_DESKTOP_MANAGED='1', WECFU_MODEL_HOME=str(assets),
                      WECFU_MODEL_PYTHON=str(python), WECFU_CV_PYTHON=str(python),
                      WECFU_ENABLE_SAM2='1')
    # User environment must never redirect a packaged model to another runtime.
    os.environ.pop('PYTHONPATH', None)
    os.environ.pop('PYTHONHOME', None)
    os.environ.pop('WECFU_SAM_DEVICE', None)
    os.environ['WECFU_ENABLE_FUSION_V2'] = '0'
    from . import runtime_paths, runtime_bootstrap, setup_models
    runtime_paths.MODEL_HOME = assets
    runtime_paths.SAM_SOURCE = assets / 'sam2/source'
    runtime_paths.SAM_CHECKPOINT = assets / 'sam2/sam2.1_hiera_tiny.pt'
    runtime_paths.MODEL_PYTHON = runtime_paths.CV_PYTHON = python
    setup_models.check(assets)
    proof = runtime_bootstrap._probe(python, assets, env=os.environ)
    runtime_bootstrap._activate(python, proof['device'])
    return manifest


class DesktopSessionGuard:
    """A per-launch capability cookie plus loopback Host/Origin validation."""
    def __init__(self, app, *, port: int, session_id: str):
        if not SESSION_PATTERN.fullmatch(session_id):
            raise ValueError('Invalid desktop session identifier')
        self.app = app
        self.session_id = session_id
        self.authority = f'127.0.0.1:{port}'
        self.origin = f'http://{self.authority}'

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'lifespan':
            return await self.app(scope, receive, send)
        if scope['type'] != 'http':
            await send({'type': 'websocket.close', 'code': 1008})
            return
        headers = {k.lower(): v for k, v in scope.get('headers', [])}
        origin = headers.get(b'origin', b'').decode('latin1')
        valid_host = headers.get(b'host', b'').decode('latin1') == self.authority
        origin_ok = not origin or origin == self.origin
        cookies = SimpleCookie()
        try:
            cookies.load(headers.get(b'cookie', b'').decode('latin1'))
            supplied = cookies[COOKIE].value if COOKIE in cookies else ''
        except Exception:
            supplied = ''
        authenticated = bool(SESSION_PATTERN.fullmatch(supplied)) and hmac.compare_digest(supplied, self.session_id)
        query = parse_qs(scope.get('query_string', b'').decode('ascii', errors='replace'))
        handshake = (scope['method'] == 'GET' and scope['path'] == '/'
                     and query.get('desktop_session') == [self.session_id])
        changing = scope['method'] not in ('GET', 'HEAD', 'OPTIONS')
        if not valid_host or not origin_ok or (changing and origin != self.origin) or not (authenticated or handshake):
            await send({'type': 'http.response.start', 'status': 403,
                        'headers': [(b'content-type', b'text/plain'), (b'cache-control', b'no-store')]})
            await send({'type': 'http.response.body', 'body': b'Desktop session access denied'})
            return

        async def guarded_send(message):
            if message['type'] == 'http.response.start':
                message = dict(message)
                response_headers = list(message.get('headers', []))
                response_headers += [(b'referrer-policy', b'no-referrer'),
                                     (b'x-content-type-options', b'nosniff'),
                                     (b'x-frame-options', b'DENY')]
                if handshake:
                    response_headers.append((b'set-cookie',
                        f'{COOKIE}={self.session_id}; Path=/; HttpOnly; SameSite=Strict'.encode('ascii')))
                message['headers'] = response_headers
            await send(message)

        return await self.app(scope, receive, guarded_send)


def emit(message):
    payload = json.dumps(message, ensure_ascii=True, separators=(',', ':'))
    if len(payload) > 4096:
        raise RuntimeError('Desktop protocol message exceeds limit')
    print(payload, flush=True)


def watch_control(server, session_id, stream, stop):
    """EOF means the owning launcher disappeared. Never keep serving orphaned."""
    while not stop.is_set():
        line = stream.readline(4097)
        if not line:
            server.should_exit = True
            return
        if len(line) > 4096 or not line.endswith(b'\n'):
            server.should_exit = True
            return
        try:
            command = json.loads(line)
        except (ValueError, UnicodeError):
            server.should_exit = True
            return
        if command == {'command': 'shutdown', 'session_id': session_id}:
            server.should_exit = True
            return
        server.should_exit = True
        return


@contextmanager
def workspace_directory(owned_root=None):
    """The shell retains cleanup ownership when it can forcibly stop Python.

    Direct host/API checks still use the ordinary Python-owned temporary root.
    A shell-provided directory must already exist and contain nothing.
    """
    if owned_root is None:
        with tempfile.TemporaryDirectory(prefix='wecfu-desktop-') as folder:
            yield Path(folder)
        return
    root = Path(owned_root)
    if (not root.is_absolute() or root.is_symlink()
            or getattr(root, 'is_junction', lambda: False)()
            or not root.is_dir() or any(root.iterdir())):
        raise RuntimeError('Desktop workspace must be a new empty owned directory')
    yield root.resolve()


def run_service(*, session_id, version, app_factory=None, workspace_root=None):
    """Bind an OS-chosen socket before starting this instance's ASGI lifespan."""
    if not SESSION_PATTERN.fullmatch(session_id):
        raise ValueError('Invalid desktop session identifier')
    import uvicorn
    if app_factory is None:
        from .server.app import build_app
        app_factory = build_app
    with workspace_directory(workspace_root) as root, socket.socket() as listener:
        (root / 'inputs').mkdir()
        (root / 'runs').mkdir()
        listener.bind(('127.0.0.1', 0))
        listener.listen(128)
        port = listener.getsockname()[1]
        app = DesktopSessionGuard(app_factory(get_root=lambda: root, web_mode=False),
                                  port=port, session_id=session_id)

        class DesktopServer(uvicorn.Server):
            async def startup(self, sockets=None):
                await super().startup(sockets=sockets)
                if self.started and not self.should_exit:
                    emit({'event': 'ready', 'session_id': session_id, 'version': version,
                          'url': f'http://127.0.0.1:{port}/?desktop_session={session_id}'})

        server = DesktopServer(uvicorn.Config(app, access_log=False, log_level='warning',
                                            timeout_graceful_shutdown=8))
        stop = threading.Event()
        control = threading.Thread(target=watch_control,
            args=(server, session_id, sys.stdin.buffer, stop), daemon=True, name='wecfu-desktop-control')
        control.start()
        try:
            server.run(sockets=[listener])
            if not server.started:
                raise RuntimeError('Desktop service did not become ready')
        finally:
            stop.set()
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--resource-root', required=True, type=Path)
    parser.add_argument('--session-id', required=True)
    parser.add_argument('--workspace-root', type=Path)
    args = parser.parse_args()
    try:
        if not SESSION_PATTERN.fullmatch(args.session_id):
            raise ValueError('Invalid desktop session identifier')
        manifest = configure_bundle(args.resource_root.resolve())
        return run_service(session_id=args.session_id, version=manifest['app_version'],
                           workspace_root=args.workspace_root)
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        # No input photos/counts or launch capability are included in diagnostics.
        message = str(exc).replace(args.session_id, '[session]')[:1800]
        emit({'event': 'error', 'session_id': args.session_id, 'message': message})
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
