"""Command-line entrypoints for wecfu."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import tempfile
import uuid
from contextlib import nullcontext
from pathlib import Path

from .pipeline import batch
from .segment import SegmentParams

_IMG_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
_BROWSER_OPEN_TIMEOUT = 5.0


async def _open_browser(url: str) -> None:
    """Keep an unresponsive OS browser launcher off the server's event loop."""
    process = None
    try:
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-I", "-c",
            "import sys, webbrowser; sys.exit(0 if webbrowser.open(sys.argv[1]) else 1)",
            url,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        if await asyncio.wait_for(process.wait(), _BROWSER_OPEN_TIMEOUT):
            print(f"Could not open a browser automatically. Open {url}", file=sys.stderr)
    except (OSError, asyncio.TimeoutError):
        print(f"Could not open a browser automatically. Open {url}", file=sys.stderr)
    finally:
        if process is not None and process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            # Bound cleanup too, including cancellation during server shutdown.
            try:
                await asyncio.wait_for(process.wait(), 1.0)
            except asyncio.TimeoutError:
                print("Browser launcher did not exit promptly.", file=sys.stderr)


def _collect_images(input_path: Path) -> list[Path]:
    if input_path.is_file():
        return [input_path]
    return sorted(
        p for p in input_path.rglob("*") if p.suffix.lower() in _IMG_EXTS and p.is_file()
    )


def _cmd_batch(args) -> int:
    input_path = Path(args.input).expanduser().resolve()
    run_dir = Path(args.out).expanduser().resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    images = _collect_images(input_path)
    if not images:
        print(f"no images found under {input_path}", file=sys.stderr)
        return 2
    params = SegmentParams()
    out_csv = batch(images, run_dir, params=params, force=args.force)
    print(f"results: {out_csv}")
    print(f"overlays: {run_dir / 'overlays'}")
    return 0


def _cmd_serve(args) -> int:
    """Single-user local GUI."""
    import uvicorn

    if getattr(args, "model_setup", True):
        from .runtime_bootstrap import ensure_ultra

        try:
            ensure_ultra()
        except RuntimeError as exc:
            print(f"Ultra setup failed: {exc}; Lite remains available.", file=sys.stderr)

    from .server.app import build_app

    temporary = args.root is None
    # Own only the directory created for this invocation. Never sweep old data
    # or orphaned sessions: another process may still use them. TemporaryDirectory
    # unlinks imported symlinks without traversing their original targets.
    workspace = (
        tempfile.TemporaryDirectory(prefix="wecfu-local-")
        if temporary else nullcontext(args.root)
    )
    with workspace as workspace_path:
        root = Path(workspace_path).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        (root / "inputs").mkdir(exist_ok=True)
        (root / "runs").mkdir(exist_ok=True)

        app = build_app(get_root=lambda: root, web_mode=False)

        class LocalServer(uvicorn.Server):
            browser_task = None

            async def startup(self, sockets=None):
                await super().startup(sockets=sockets)
                # This instance's lifespan and socket binding must both succeed.
                # Never probe an existing HTTP service to decide readiness.
                if not self.started or self.should_exit:
                    return
                port = self.servers[0].sockets[0].getsockname()[1]
                url = f"http://127.0.0.1:{port}/?launch={uuid.uuid4().hex}"
                print(f"wecfu serving at {url}  (workspace: {root})")
                if temporary:
                    print("Temporary session: export your results before stopping the server.")
                if args.open:
                    self.browser_task = asyncio.create_task(_open_browser(url))

            async def shutdown(self, sockets=None):
                try:
                    if self.browser_task is not None:
                        self.browser_task.cancel()
                        await self.browser_task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    print("Browser launcher failed; closing the server normally.", file=sys.stderr)
                finally:
                    await super().shutdown(sockets=sockets)

        config = uvicorn.Config(app, host="127.0.0.1", port=args.port, log_level="info")
        try:
            LocalServer(config).run()
        except KeyboardInterrupt:
            # Match uvicorn.run(): Ctrl-C is a normal local GUI exit. Keep this
            # narrow so bind failures and application errors still propagate.
            pass
    return 0


def _cmd_web(args) -> int:
    """Multi-visitor web mode (Hugging Face Spaces and similar)."""
    import uvicorn

    from .server.web import build_web_app

    sessions_root = Path(
        args.sessions_root
        or os.environ.get("WECFU_SESSIONS_ROOT")
        # Cross-platform temp dir: /tmp on Unix, %TEMP% on Windows.
        or (Path(tempfile.gettempdir()) / "wecfu_sessions")
    ).expanduser().resolve()

    app = build_web_app(sessions_root)
    print(
        f"wecfu (web mode) serving at http://{args.host}:{args.port}  "
        f"(sessions: {sessions_root})"
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(prog="wecfu")
    sub = p.add_subparsers(dest="cmd", required=True)

    pb = sub.add_parser("batch", help="non-interactive batch run")
    pb.add_argument("input", help="file or directory of plate photos")
    pb.add_argument("--out", required=True, help="output run directory")
    pb.add_argument(
        "--force", action="store_true", help="reprocess images even if outputs exist"
    )
    pb.set_defaults(func=_cmd_batch)

    ps = sub.add_parser("serve", help="launch the single-user local web GUI")
    ps.add_argument(
        "--root",
        default=None,
        help="keep a persistent workspace containing inputs/ and runs/; "
             "otherwise use a fresh temporary session, cleared when the server stops",
    )
    ps.add_argument("--port", type=int, default=8765)
    ps.add_argument("--no-open", dest="open", action="store_false")
    ps.add_argument(
        "--no-model-setup", dest="model_setup", action="store_false",
        help="skip automatic Ultra setup for offline use; configured models remain available",
    )
    ps.set_defaults(func=_cmd_serve, open=True, model_setup=True)

    pw = sub.add_parser(
        "web",
        help="multi-visitor web mode with per-session isolation (for deployment)",
    )
    pw.add_argument(
        "--sessions-root",
        default=None,
        help="root dir for per-session workspaces "
             "(default: $WECFU_SESSIONS_ROOT or <tempdir>/wecfu_sessions)",
    )
    pw.add_argument("--host", default="0.0.0.0",
                    help="bind host (default: 0.0.0.0 — for containers)")
    pw.add_argument("--port", type=int, default=7860,
                    help="bind port (default: 7860 — Hugging Face Spaces convention)")
    pw.set_defaults(func=_cmd_web)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
