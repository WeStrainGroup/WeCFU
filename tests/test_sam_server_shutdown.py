from fastapi.testclient import TestClient
import asyncio
import pytest
from wecfu.server.app import build_app
from wecfu.server import sam_warm_pool
from wecfu.server import web


def test_server_shutdown_retires_resident_workers(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(sam_warm_pool.POOL, 'shutdown', lambda: calls.append('shutdown'))
    app = build_app(lambda: tmp_path)
    for _ in range(2):
        with TestClient(app):
            pass
    assert calls == ['shutdown', 'shutdown']


@pytest.mark.parametrize('body_fails', [False, True])
def test_web_shutdown_awaits_cleanup_and_retires_workers(monkeypatch, tmp_path, body_fails):
    events = []

    async def cleanup(root):
        assert root == tmp_path.resolve()
        events.append('cleanup-started')
        try:
            await asyncio.Event().wait()
        finally:
            events.append('cleanup-stopped')

    monkeypatch.setattr(web, '_cleanup_loop', cleanup)
    monkeypatch.setattr(sam_warm_pool.POOL, 'shutdown', lambda: events.append('shutdown'))
    app = web.build_web_app(tmp_path)
    for _ in range(2):
        if body_fails:
            with pytest.raises(RuntimeError, match='synthetic client failure'):
                with TestClient(app):
                    raise RuntimeError('synthetic client failure')
        else:
            with TestClient(app):
                pass
    assert events == ['cleanup-started', 'cleanup-stopped', 'shutdown'] * 2
