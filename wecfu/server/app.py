"""FastAPI backend for the CFU counter GUI."""

from __future__ import annotations

import io
import json
import shutil
import time
import zipfile
from dataclasses import asdict
from pathlib import Path
from typing import List, Optional

import cv2
import numpy as np
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..naming import parse as parse_name
from ..overlay import render
from ..pipeline import process_image
from ..plate import PlateCircle
from ..segment import Detection, SegmentParams, _white_colony_mask

_IMG_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
_STATIC = Path(__file__).parent / "static"


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
        return "default"
    subdirs = [p for p in inputs_root.iterdir() if p.is_dir()]
    if not subdirs:
        return "default"
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


def build_app(root: Path) -> FastAPI:
    root.mkdir(parents=True, exist_ok=True)
    (root / "inputs").mkdir(exist_ok=True)
    (root / "runs").mkdir(exist_ok=True)

    app = FastAPI(title="CFU counter")

    # ─── batch / image listing ──────────────────────────────────────────────

    @app.get("/api/batches")
    def list_batches():
        return {
            "batches": sorted(p.name for p in (root / "inputs").iterdir() if p.is_dir()),
            "default": _default_batch(root),
        }

    @app.get("/api/batch/{batch}/images")
    def list_images(batch: str):
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
            low_conf = False
            method = None
            notes = ""
            if state:
                count = len(state.get("detections", []))
                reviewed = state.get("reviewed", False)
                low_conf = state.get("diagnostics", {}).get("low_confidence", False)
                method = state.get("method")
                notes = state.get("notes", "")
            items.append({
                "name": p.name,
                "processed": state is not None,
                "count": count,
                "reviewed": reviewed,
                "low_confidence": low_conf,
                "method": method,
                "notes": notes,
            })
        return {"images": items}

    # ─── ingest ────────────────────────────────────────────────────────────

    @app.post("/api/ingest")
    def ingest(body: IngestBody):
        batch = body.batch or time.strftime("upload_%Y%m%d_%H%M%S")
        dst = root / "inputs" / batch
        dst.mkdir(parents=True, exist_ok=True)
        n = 0
        for raw in body.paths:
            src = Path(raw).expanduser().resolve()
            if not src.exists():
                continue
            if src.is_file() and src.suffix.lower() in _IMG_EXTS:
                target = dst / src.name
                if not target.exists():
                    target.symlink_to(src)
                    n += 1
            elif src.is_dir():
                for f in src.rglob("*"):
                    if f.is_file() and f.suffix.lower() in _IMG_EXTS:
                        target = dst / f.name
                        if not target.exists():
                            target.symlink_to(f)
                            n += 1
        return {"batch": batch, "linked": n}

    @app.post("/api/upload")
    async def upload(batch: str = Form(...), files: list[UploadFile] = File(...)):
        dst = root / "inputs" / batch
        dst.mkdir(parents=True, exist_ok=True)
        n = 0
        for f in files:
            if Path(f.filename).suffix.lower() not in _IMG_EXTS:
                continue
            out = dst / Path(f.filename).name
            with out.open("wb") as fh:
                shutil.copyfileobj(f.file, fh)
            n += 1
        return {"batch": batch, "uploaded": n}

    # ─── processing ─────────────────────────────────────────────────────────

    @app.post("/api/batch/{batch}/run")
    def run_batch(batch: str, params: Optional[ParamsBody] = None, force: bool = False):
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
        img_path = _image_for(root, batch, name)
        run_dir = root / "runs" / batch
        run_dir.mkdir(parents=True, exist_ok=True)
        process_image(img_path, run_dir, params=_params_from_body(params), force=True)
        return {"ok": True}

    @app.post("/api/batch/{batch}/image/{name}/sam")
    def run_sam(batch: str, name: str):
        from ..sam_refine import sam_segment

        img_path = _image_for(root, batch, name)
        img = cv2.imdecode(np.fromfile(str(img_path), dtype=np.uint8), cv2.IMREAD_COLOR)
        state = _load_state(root, batch, name)
        plate = PlateCircle(**state["plate"])
        try:
            dets = sam_segment(img, plate)
        except RuntimeError as e:
            raise HTTPException(400, str(e))
        state["detections"] = [d.asdict() for d in dets]
        state["method"] = "sam"
        state["reviewed"] = False
        _save_state(root, batch, name, state)
        _rerender(root, batch, name, state)
        return {"count": len(dets)}

    # ─── mask preview (live tuning) ─────────────────────────────────────────

    @app.post("/api/batch/{batch}/image/{name}/mask_preview.png")
    def mask_preview(batch: str, name: str, params: ParamsBody):
        img_path = _image_for(root, batch, name)
        img = cv2.imdecode(np.fromfile(str(img_path), dtype=np.uint8), cv2.IMREAD_COLOR)
        # Reuse the existing plate detection if we already have one — cheaper.
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
        # Tint: green where mask is on, dim the rest. Then crop to plate bbox.
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
        return _load_state(root, batch, name)

    @app.post("/api/batch/{batch}/image/{name}/detections")
    def add_det(batch: str, name: str, body: AddDetectionBody):
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
        _rerender(root, batch, name, state)
        return {"id": next_id}

    @app.delete("/api/batch/{batch}/image/{name}/detections/{det_id}")
    def delete_det(batch: str, name: str, det_id: int):
        state = _load_state(root, batch, name)
        before = len(state["detections"])
        state["detections"] = [d for d in state["detections"] if d["id"] != det_id]
        if len(state["detections"]) == before:
            raise HTTPException(404, f"detection {det_id} not found")
        state["reviewed"] = True
        _save_state(root, batch, name, state)
        _rerender(root, batch, name, state)
        return {"ok": True}

    @app.post("/api/batch/{batch}/image/{name}/reviewed")
    def mark_reviewed(batch: str, name: str, reviewed: bool = True):
        state = _load_state(root, batch, name)
        state["reviewed"] = reviewed
        _save_state(root, batch, name, state)
        return {"ok": True}

    @app.put("/api/batch/{batch}/image/{name}/notes")
    def set_notes(batch: str, name: str, body: NotesBody):
        state = _load_state(root, batch, name)
        state["notes"] = body.notes
        _save_state(root, batch, name, state)
        return {"ok": True}

    # ─── static image serving ──────────────────────────────────────────────

    @app.get("/api/batch/{batch}/image/{name}/raw")
    def serve_raw(batch: str, name: str):
        return FileResponse(_image_for(root, batch, name))

    @app.get("/api/batch/{batch}/image/{name}/overlay")
    def serve_overlay(batch: str, name: str):
        p = _overlay_path(root, batch, name)
        if not p.exists():
            raise HTTPException(404, "overlay missing — run first")
        return FileResponse(p)

    # ─── export ────────────────────────────────────────────────────────────

    def _build_csv(batch: str) -> str:
        import csv
        in_dir = root / "inputs" / batch
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            "filename", "plate", "gram", "medium", "dilution",
            "atmo", "day", "rep", "timestamp",
            "cfu_count", "mean_radius_px", "plate_radius_px",
            "reviewed", "method", "n_manual",
            "low_confidence", "notes",
        ])
        for p in sorted(in_dir.iterdir()):
            if p.suffix.lower() not in _IMG_EXTS:
                continue
            det_p = _det_path(root, batch, p.name)
            state = json.loads(det_p.read_text()) if det_p.exists() else None
            meta = parse_name(p.name)
            if not state:
                writer.writerow([
                    p.name,
                    meta.plate if meta else "",
                    meta.gram if meta else "",
                    meta.medium if meta else "",
                    meta.dilution if meta else "",
                    meta.atmo if meta else "",
                    meta.day if meta else "",
                    meta.rep if meta else "",
                    meta.timestamp if meta else "",
                    "", "", "", False, "", 0, "", "",
                ])
                continue
            dets = state["detections"]
            diag = state.get("diagnostics", {})
            writer.writerow([
                p.name,
                meta.plate if meta else "",
                meta.gram if meta else "",
                meta.medium if meta else "",
                meta.dilution if meta else "",
                meta.atmo if meta else "",
                meta.day if meta else "",
                meta.rep if meta else "",
                meta.timestamp if meta else "",
                len(dets),
                diag.get("mean_radius_px", ""),
                state.get("plate", {}).get("r", ""),
                state.get("reviewed", False),
                state.get("method", ""),
                sum(1 for d in dets if d.get("source") == "manual"),
                diag.get("low_confidence", False),
                state.get("notes", ""),
            ])
        return buf.getvalue()

    @app.get("/api/batch/{batch}/export.csv")
    def export_csv(batch: str):
        in_dir = root / "inputs" / batch
        if not in_dir.exists():
            raise HTTPException(404, "batch not found")
        return Response(
            content=_build_csv(batch),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="cfu_{batch}.csv"'},
        )

    @app.get("/api/batch/{batch}/export.zip")
    def export_bundle(batch: str):
        """Bundle CSV + every annotated overlay + per-image JSON in one zip."""
        in_dir = root / "inputs" / batch
        if not in_dir.exists():
            raise HTTPException(404, "batch not found")
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(f"cfu_{batch}.csv", _build_csv(batch))
            ov_dir = root / "runs" / batch / "overlays"
            det_dir = root / "runs" / batch / "detections"
            if ov_dir.exists():
                for p in sorted(ov_dir.glob("*.png")):
                    zf.write(p, arcname=f"overlays/{p.name}")
            if det_dir.exists():
                for p in sorted(det_dir.glob("*.json")):
                    zf.write(p, arcname=f"detections/{p.name}")
        out.seek(0)
        return Response(
            content=out.getvalue(),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="cfu_{batch}.zip"'},
        )

    # ─── frontend ──────────────────────────────────────────────────────────
    app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")

    @app.get("/")
    def index():
        return FileResponse(_STATIC / "index.html")

    return app
