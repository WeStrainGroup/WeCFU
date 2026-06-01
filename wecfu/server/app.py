"""FastAPI backend for the WeCFU GUI.

`build_app` accepts a `get_root` callable that returns the workspace directory
for the *current request*. In single-user local mode (CLI) this is a constant.
In web mode (multi-visitor HF Space) it resolves to a per-session directory
via a cookie-driven middleware (see `wecfu.server.web`).

The "batch" concept still exists internally for storage organisation but is
auto-managed and not surfaced in the UI.
"""

from __future__ import annotations

import io
import json
import shutil
import time
import zipfile
from pathlib import Path
from typing import Callable, List, Optional

import cv2
import numpy as np
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..overlay import render
from ..pipeline import process_image
from ..plate import PlateCircle
from ..segment import Detection, SegmentParams, _white_colony_mask

_IMG_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
_STATIC = Path(__file__).parent / "static"

# Web-mode upload limits (per request body & per session). Ignored in local mode.
WEB_MAX_BYTES = 400 * 1024 * 1024   # 400 MB per upload request
WEB_MAX_IMAGES = 100                # cap on images per session


class IngestBody(BaseModel):
    paths: List[str]
    batch: Optional[str] = None


class AddDetectionBody(BaseModel):
    cx: float
    cy: float
    r: float


class NotesBody(BaseModel):
    notes: str


class ParamsBody(BaseModel):
    plate_inset: float = SegmentParams.plate_inset
    min_value: int = SegmentParams.min_value
    max_saturation: int = SegmentParams.max_saturation
    min_circularity: float = SegmentParams.min_circularity
    min_area_frac: float = SegmentParams.min_area_frac
    peak_min_distance: int = SegmentParams.peak_min_distance


def _default_batch(root: Path) -> str:
    inputs_root = root / "inputs"
    if not inputs_root.exists():
        return time.strftime("session_%Y%m%d_%H%M%S")
    subdirs = [p for p in inputs_root.iterdir() if p.is_dir()]
    if not subdirs:
        return time.strftime("session_%Y%m%d_%H%M%S")
    return max(subdirs, key=lambda p: p.stat().st_mtime).name


def _image_for(root: Path, batch: str, name: str) -> Path:
    p = root / "inputs" / batch / name
    if not p.exists():
        raise HTTPException(404, f"image not found: {name}")
    return p


def _det_path(root: Path, batch: str, name: str) -> Path:
    return root / "runs" / batch / "detections" / f"{Path(name).stem}.json"


def _overlay_path(root: Path, batch: str, name: str) -> Path:
    return root / "runs" / batch / "overlays" / f"{Path(name).stem}.png"


def _load_state(root: Path, batch: str, name: str) -> dict:
    p = _det_path(root, batch, name)
    if not p.exists():
        raise HTTPException(404, f"detections not run for {name}")
    return json.loads(p.read_text())


def _save_state(root: Path, batch: str, name: str, state: dict) -> None:
    p = _det_path(root, batch, name)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2))


def _rerender(root: Path, batch: str, name: str, state: dict) -> None:
    img_path = _image_for(root, batch, name)
    img = cv2.imdecode(np.fromfile(str(img_path), dtype=np.uint8), cv2.IMREAD_COLOR)
    plate = PlateCircle(**state["plate"])
    dets = [Detection(**d) for d in state["detections"]]
    overlay = render(img, dets, plate, crop=True)
    op = _overlay_path(root, batch, name)
    op.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(op), overlay)


def _params_from_body(body: Optional[ParamsBody]) -> SegmentParams:
    if body is None:
        return SegmentParams()
    return SegmentParams(
        plate_inset=body.plate_inset,
        min_value=body.min_value,
        max_saturation=body.max_saturation,
        min_circularity=body.min_circularity,
        min_area_frac=body.min_area_frac,
        peak_min_distance=body.peak_min_distance,
    )


def _link_or_copy(src: Path, target: Path) -> bool:
    """Make `target` point at / contain `src`. Returns True if it created
    a new entry, False if it already existed.

    Prefers a symlink (instant, zero disk) but falls back to a real copy
    when symlinks aren't permitted — most importantly on Windows, where
    os.symlink needs Administrator rights or Developer Mode. Either way
    the user's original file is never modified.
    """
    if target.exists():
        return False
    try:
        target.symlink_to(src)
    except (OSError, NotImplementedError):
        shutil.copy2(src, target)
    return True


def _count_images(root: Path) -> int:
    """How many images are currently stored under this workspace (across all batches)."""
    inputs = root / "inputs"
    if not inputs.exists():
        return 0
    total = 0
    for batch_dir in inputs.iterdir():
        if not batch_dir.is_dir():
            continue
        total += sum(1 for f in batch_dir.iterdir()
                     if f.is_file() and f.suffix.lower() in _IMG_EXTS)
    return total


def build_app(get_root: Callable[[], Path], web_mode: bool = False) -> FastAPI:
    """Build the FastAPI app.

    Args:
      get_root: zero-arg callable returning the workspace `Path` for the
        current request. In local mode this is `lambda: fixed_path`. In web
        mode the session middleware sets a contextvar and `get_root` reads
        it (so each request gets its own per-visitor workspace).
      web_mode: enables upload size caps and disables filesystem ingest
        (the /api/ingest endpoint would have no meaning on a server with
        no access to the visitor's filesystem).
    """
    app = FastAPI(title="WeCFU")

    @app.get("/api/config")
    def get_config():
        """Frontend feature flags."""
        return {
            "web_mode": web_mode,
            "max_images": WEB_MAX_IMAGES if web_mode else None,
            "max_bytes": WEB_MAX_BYTES if web_mode else None,
        }

    @app.get("/api/batches")
    def list_batches():
        root = get_root()
        (root / "inputs").mkdir(parents=True, exist_ok=True)
        return {
            "batches": sorted(p.name for p in (root / "inputs").iterdir() if p.is_dir()),
            "default": _default_batch(root),
        }

    @app.get("/api/batch/{batch}/images")
    def list_images(batch: str):
        root = get_root()
        in_dir = root / "inputs" / batch
        if not in_dir.exists():
            raise HTTPException(404, "batch not found")
        items = []
        for p in sorted(in_dir.iterdir()):
            if p.suffix.lower() not in _IMG_EXTS:
                continue
            det_path = _det_path(root, batch, p.name)
            state = json.loads(det_path.read_text()) if det_path.exists() else None
            count = 0
            reviewed = False
            notes = ""
            if state:
                count = len(state.get("detections", []))
                reviewed = state.get("reviewed", False)
                notes = state.get("notes", "")
            items.append({
                "name": p.name,
                "processed": state is not None,
                "count": count,
                "reviewed": reviewed,
                "notes": notes,
            })
        return {"images": items}

    # ─── ingest (local mode only) ──────────────────────────────────────────

    @app.post("/api/ingest")
    def ingest(body: IngestBody):
        if web_mode:
            raise HTTPException(
                403, "Path ingest is disabled in web mode — drag-drop files instead."
            )
        root = get_root()
        batch = body.batch or time.strftime("session_%Y%m%d_%H%M%S")
        dst = root / "inputs" / batch
        dst.mkdir(parents=True, exist_ok=True)
        n = 0
        for raw in body.paths:
            src = Path(raw).expanduser().resolve()
            if not src.exists():
                continue
            if src.is_file() and src.suffix.lower() in _IMG_EXTS:
                if _link_or_copy(src, dst / src.name):
                    n += 1
            elif src.is_dir():
                for f in src.rglob("*"):
                    if f.is_file() and f.suffix.lower() in _IMG_EXTS:
                        if _link_or_copy(f, dst / f.name):
                            n += 1
        return {"batch": batch, "linked": n}

    @app.post("/api/upload")
    async def upload(batch: str = Form(...), files: list[UploadFile] = File(...)):
        root = get_root()
        if web_mode:
            existing = _count_images(root)
            if existing + len(files) > WEB_MAX_IMAGES:
                raise HTTPException(
                    413,
                    f"Per-session limit is {WEB_MAX_IMAGES} images "
                    f"(you have {existing}, tried to add {len(files)}).",
                )
        dst = root / "inputs" / batch
        dst.mkdir(parents=True, exist_ok=True)
        n = 0
        running_bytes = 0
        for f in files:
            if Path(f.filename).suffix.lower() not in _IMG_EXTS:
                continue
            out = dst / Path(f.filename).name
            with out.open("wb") as fh:
                while True:
                    chunk = await f.read(1 << 20)  # 1 MB
                    if not chunk:
                        break
                    running_bytes += len(chunk)
                    if web_mode and running_bytes > WEB_MAX_BYTES:
                        fh.close()
                        out.unlink(missing_ok=True)
                        raise HTTPException(
                            413, f"Upload exceeds {WEB_MAX_BYTES // 1024 // 1024} MB cap."
                        )
                    fh.write(chunk)
            n += 1
        return {"batch": batch, "uploaded": n}

    # ─── processing ─────────────────────────────────────────────────────────

    @app.post("/api/batch/{batch}/run")
    def run_batch(batch: str, params: Optional[ParamsBody] = None, force: bool = False):
        root = get_root()
        in_dir = root / "inputs" / batch
        if not in_dir.exists():
            raise HTTPException(404, "batch not found")
        run_dir = root / "runs" / batch
        run_dir.mkdir(parents=True, exist_ok=True)
        sp = _params_from_body(params)
        processed = 0
        for p in sorted(in_dir.iterdir()):
            if p.suffix.lower() not in _IMG_EXTS:
                continue
            try:
                process_image(p, run_dir, params=sp, force=force)
                processed += 1
            except Exception as exc:  # noqa: BLE001
                print(f"[error] {p.name}: {exc}")
        return {"processed": processed}

    @app.post("/api/batch/{batch}/image/{name}/run")
    def run_one(batch: str, name: str, params: Optional[ParamsBody] = None):
        root = get_root()
        img_path = _image_for(root, batch, name)
        run_dir = root / "runs" / batch
        run_dir.mkdir(parents=True, exist_ok=True)
        process_image(img_path, run_dir, params=_params_from_body(params), force=True)
        return {"ok": True}

    @app.post("/api/batch/{batch}/image/{name}/mask_preview.png")
    def mask_preview(batch: str, name: str, params: ParamsBody):
        root = get_root()
        img_path = _image_for(root, batch, name)
        img = cv2.imdecode(np.fromfile(str(img_path), dtype=np.uint8), cv2.IMREAD_COLOR)
        try:
            state = _load_state(root, batch, name)
            plate = PlateCircle(**state["plate"])
        except HTTPException:
            from ..plate import detect_plate
            plate = detect_plate(img)
        sp = _params_from_body(params)
        h, w = img.shape[:2]
        plate_mask = plate.mask((h, w), shrink=sp.plate_inset)
        bw = _white_colony_mask(img, plate_mask, sp.min_value, sp.max_saturation)
        out = img.copy()
        green = np.zeros_like(out)
        green[..., 1] = 255
        out = np.where(bw[..., None] > 0, (out * 0.4 + green * 0.6).astype(np.uint8), out)
        from ..overlay import _crop_to_plate
        out, _, _ = _crop_to_plate(out, plate)
        ok, buf = cv2.imencode(".png", out)
        if not ok:
            raise HTTPException(500, "encode failed")
        return Response(content=buf.tobytes(), media_type="image/png")

    # ─── detection CRUD ─────────────────────────────────────────────────────

    @app.get("/api/batch/{batch}/image/{name}/detections")
    def get_state(batch: str, name: str):
        return _load_state(get_root(), batch, name)

    @app.post("/api/batch/{batch}/image/{name}/detections")
    def add_det(batch: str, name: str, body: AddDetectionBody):
        root = get_root()
        state = _load_state(root, batch, name)
        next_id = (max((d["id"] for d in state["detections"]), default=0) + 1)
        d = Detection(
            id=next_id,
            cx=body.cx,
            cy=body.cy,
            r=body.r,
            score=1.0,
            accepted=True,
            source="manual",
        )
        state["detections"].append(d.asdict())
        state["reviewed"] = True
        _save_state(root, batch, name, state)
        return {"id": next_id}

    @app.delete("/api/batch/{batch}/image/{name}/detections/{det_id}")
    def delete_det(batch: str, name: str, det_id: int):
        root = get_root()
        state = _load_state(root, batch, name)
        before = len(state["detections"])
        state["detections"] = [d for d in state["detections"] if d["id"] != det_id]
        if len(state["detections"]) == before:
            raise HTTPException(404, f"detection {det_id} not found")
        state["reviewed"] = True
        _save_state(root, batch, name, state)
        return {"ok": True}

    @app.post("/api/batch/{batch}/image/{name}/reviewed")
    def mark_reviewed(batch: str, name: str, reviewed: bool = True):
        root = get_root()
        state = _load_state(root, batch, name)
        state["reviewed"] = reviewed
        _save_state(root, batch, name, state)
        return {"ok": True}

    @app.put("/api/batch/{batch}/image/{name}/notes")
    def set_notes(batch: str, name: str, body: NotesBody):
        root = get_root()
        state = _load_state(root, batch, name)
        state["notes"] = body.notes
        _save_state(root, batch, name, state)
        return {"ok": True}

    # ─── static image serving ──────────────────────────────────────────────

    @app.get("/api/batch/{batch}/image/{name}/raw")
    def serve_raw(batch: str, name: str):
        return FileResponse(_image_for(get_root(), batch, name))

    @app.get("/api/batch/{batch}/image/{name}/overlay")
    def serve_overlay(batch: str, name: str):
        root = get_root()
        state = _load_state(root, batch, name)
        op = _overlay_path(root, batch, name)
        if not op.exists() or op.stat().st_mtime < _det_path(root, batch, name).stat().st_mtime:
            _rerender(root, batch, name, state)
        return FileResponse(op)

    # ─── export ────────────────────────────────────────────────────────────

    def _build_csv(root: Path, batch: str) -> str:
        """Slim CSV: only the columns users actually care about."""
        import csv
        in_dir = root / "inputs" / batch
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            "filename",
            "total_count",
            "machine_count",
            "n_removed",
            "n_added",
            "notes",
        ])
        for p in sorted(in_dir.iterdir()):
            if p.suffix.lower() not in _IMG_EXTS:
                continue
            det_p = _det_path(root, batch, p.name)
            state = json.loads(det_p.read_text()) if det_p.exists() else None
            if not state:
                writer.writerow([p.name, "", "", "", "", ""])
                continue
            dets = state["detections"]
            cv_remaining = sum(1 for d in dets if d.get("source") == "cv")
            manual = sum(1 for d in dets if d.get("source") == "manual")
            machine_initial = state.get("machine_count_initial", cv_remaining)
            writer.writerow([
                p.name,
                len(dets),
                machine_initial,
                machine_initial - cv_remaining,
                manual,
                state.get("notes", ""),
            ])
        return buf.getvalue()

    @app.get("/api/batch/{batch}/export.csv")
    def export_csv(batch: str, filename: Optional[str] = None):
        root = get_root()
        in_dir = root / "inputs" / batch
        if not in_dir.exists():
            raise HTTPException(404, "batch not found")
        fname = filename or f"wecfu_{batch}.csv"
        if not fname.lower().endswith(".csv"):
            fname += ".csv"
        return Response(
            content=_build_csv(root, batch),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{fname}"'},
        )

    @app.get("/api/batch/{batch}/export.zip")
    def export_bundle(batch: str, filename: Optional[str] = None):
        root = get_root()
        in_dir = root / "inputs" / batch
        if not in_dir.exists():
            raise HTTPException(404, "batch not found")
        for p in sorted(in_dir.iterdir()):
            if p.suffix.lower() not in _IMG_EXTS:
                continue
            det_p = _det_path(root, batch, p.name)
            if not det_p.exists():
                continue
            state = json.loads(det_p.read_text())
            op = _overlay_path(root, batch, p.name)
            if not op.exists() or op.stat().st_mtime < det_p.stat().st_mtime:
                _rerender(root, batch, p.name, state)
        out = io.BytesIO()
        base = (filename or f"wecfu_{batch}").rstrip(".zip")
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(f"{base}.csv", _build_csv(root, batch))
            ov_dir = root / "runs" / batch / "overlays"
            det_dir = root / "runs" / batch / "detections"
            if ov_dir.exists():
                for p in sorted(ov_dir.glob("*.png")):
                    zf.write(p, arcname=f"overlays/{p.name}")
            if det_dir.exists():
                for p in sorted(det_dir.glob("*.json")):
                    zf.write(p, arcname=f"detections/{p.name}")
        out.seek(0)
        fname = (filename or f"wecfu_{batch}")
        if not fname.lower().endswith(".zip"):
            fname += ".zip"
        return Response(
            content=out.getvalue(),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{fname}"'},
        )

    # ─── frontend ──────────────────────────────────────────────────────────
    app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")

    @app.get("/")
    def index():
        return FileResponse(_STATIC / "index.html")

    return app
