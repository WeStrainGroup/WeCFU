"""Web-mode wrapper around the WeCFU FastAPI app.

Designed for Hugging Face Spaces and similar shared deployments.

What it adds on top of the local app:

* A per-visitor session cookie (`wecfu_session`). Each visitor's workspace
  lives at `<sessions_root>/<session_token>/`, completely isolated from
  every other visitor.
* A background task that wakes up every minute and deletes any session
  whose directory has been idle for more than `SESSION_TTL_SECONDS`.
* `/api/ingest` (local-path symlinks) is refused via `web_mode=True`.
* Upload size and count caps are enforced (see app.py).

Note that we deliberately do NOT use any database or external storage.
Sessions are ephemeral; closing the tab and waiting 60 minutes leaves
zero trace on the server.
"""

from __future__ import annotations

import asyncio
import secrets
import shutil
import time
from contextlib import asynccontextmanager
from contextvars import ContextVar
from pathlib import Path

from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware

from .app import build_app

SESSION_COOKIE = "wecfu_session"
SESSION_TTL_SECONDS = 60 * 60        # 1 hour idle → delete
CLEANUP_INTERVAL_SECONDS = 60        # check once a minute

# Set by the middleware on each request; read by the closure passed to
# build_app(get_root=...).
_root_cv: ContextVar[Path] = ContextVar("wecfu_root")


def _new_token() -> str:
    return secrets.token_urlsafe(18)


def _is_valid_token(tok: str) -> bool:
    """Reject anything that could escape the sessions dir (../, slashes, etc)."""
    if not tok or len(tok) > 64:
        return False
    return all(c.isalnum() or c in "-_" for c in tok)


class SessionMiddleware(BaseHTTPMiddleware):
    """Resolve the visitor's session and bind a per-request root contextvar.

    Each visitor is identified by a cookie. If the cookie is missing or
    malformed, a fresh token is minted on the response.
    """

    def __init__(self, app, sessions_root: Path):
        super().__init__(app)
        self.sessions_root = sessions_root

    async def dispatch(self, request: Request, call_next):
        token = request.cookies.get(SESSION_COOKIE)
        is_new = not (token and _is_valid_token(token))
        if is_new:
            token = _new_token()
        root = self.sessions_root / token
        root.mkdir(parents=True, exist_ok=True)
        # Bump mtime so the cleanup task knows this session is alive.
        root.touch()
        _root_cv.set(root)

        response = await call_next(request)
        if is_new:
            # HttpOnly so JS can't steal it; SameSite=Lax keeps it usable
            # for direct navigation from external sites.
            response.set_cookie(
                SESSION_COOKIE, token,
                max_age=SESSION_TTL_SECONDS,
                httponly=True, samesite="lax", secure=False,  # HF terminates TLS
            )
        return response


async def _cleanup_loop(sessions_root: Path):
    """Background coroutine: every minute, delete idle session dirs."""
    while True:
        try:
            now = time.time()
            if sessions_root.exists():
                for sub in sessions_root.iterdir():
                    if not sub.is_dir():
                        continue
                    age = now - sub.stat().st_mtime
                    if age > SESSION_TTL_SECONDS:
                        try:
                            shutil.rmtree(sub)
                        except Exception as exc:  # noqa: BLE001
                            print(f"[cleanup] failed to remove {sub}: {exc}")
        except Exception as exc:  # noqa: BLE001
            print(f"[cleanup loop] {exc}")
        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)


def build_web_app(sessions_root: Path) -> FastAPI:
    """Build the multi-visitor web app."""
    sessions_root = sessions_root.expanduser().resolve()
    sessions_root.mkdir(parents=True, exist_ok=True)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(_cleanup_loop(sessions_root))
        try:
            yield
        finally:
            task.cancel()

    app = build_app(get_root=lambda: _root_cv.get(), web_mode=True)
    app.router.lifespan_context = lifespan
    app.add_middleware(SessionMiddleware, sessions_root=sessions_root)
    return app
