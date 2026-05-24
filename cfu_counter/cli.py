"""Command-line entrypoints for cfu-counter."""

from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

from .pipeline import batch
from .segment import SegmentParams

_IMG_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}


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
    import uvicorn

    from .server.app import build_app

    root = Path(args.root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    app = build_app(root)
    url = f"http://127.0.0.1:{args.port}"
    if args.open:
        webbrowser.open(url)
    print(f"cfu-counter serving at {url}  (workspace: {root})")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")
    return 0


def _cmd_sam(args) -> int:
    import cv2
    import numpy as np

    from .plate import detect_plate
    from .sam_refine import sam_segment

    img = cv2.imdecode(np.fromfile(args.image, dtype=np.uint8), cv2.IMREAD_COLOR)
    plate = detect_plate(img)
    dets = sam_segment(img, plate)
    print(f"SAM detections: {len(dets)}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(prog="cfu-counter")
    sub = p.add_subparsers(dest="cmd", required=True)

    pb = sub.add_parser("batch", help="non-interactive batch run")
    pb.add_argument("input", help="file or directory of plate photos")
    pb.add_argument("--out", required=True, help="output run directory")
    pb.add_argument(
        "--force", action="store_true", help="reprocess images even if outputs exist"
    )
    pb.set_defaults(func=_cmd_batch)

    ps = sub.add_parser("serve", help="launch the local web GUI")
    ps.add_argument(
        "--root",
        default="~/claude_code_workspace/WeF/cfu-counter/data",
        help="workspace root containing inputs/ and runs/",
    )
    ps.add_argument("--port", type=int, default=8765)
    ps.add_argument("--no-open", dest="open", action="store_false")
    ps.set_defaults(func=_cmd_serve, open=True)

    psam = sub.add_parser("sam", help="single-image SAM run (debug)")
    psam.add_argument("image")
    psam.set_defaults(func=_cmd_sam)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
