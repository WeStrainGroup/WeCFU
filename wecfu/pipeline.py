"""Orchestrate plate detection, segmentation and editable state persistence."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Iterable, List, Optional

import cv2
import numpy as np
import pandas as pd

from .overlay import render
from .plate import PlateCircle, detect_plate
from .segment import Detection, SegmentParams, segment


def atomic_write_json(path: Path, payload: dict) -> None:
    """Replace one complete UTF-8 state; readers never see a partial write."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _load_detections(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _save_detections(
    path: Path,
    detections: List[Detection],
    plate: PlateCircle,
    diagnostics: dict,
    reviewed: bool,
    params: SegmentParams,
    machine_count_initial: int,
    previous: Optional[dict] = None,
    image_size: Optional[dict] = None,
    engine: str = "baseline",
) -> None:
    previous = previous or {}
    payload = {
        "plate": asdict(plate),
        "detections": [d.asdict() for d in detections],
        "diagnostics": {**diagnostics, "algorithm": engine},
        "reviewed": reviewed,
        "machine_count_initial": machine_count_initial,
        "params": asdict(params),
        "count_params": asdict(params),
        "count_engine": engine,
        "count_model": None,
        "notes": previous.get("notes", ""),
        "mode": "auto",
        "counted": True,
        "plate_manual": previous.get("plate_manual", False),
        "revision": previous.get("revision", 0) + 1,
    }
    if image_size:
        payload["image_size"] = image_size
    atomic_write_json(path, payload)


def process_image(
    img_path: Path,
    run_dir: Path,
    params: SegmentParams = None,
    force: bool = False,
    *,
    write_overlay: bool = True,
    plate_override: Optional[PlateCircle] = None,
    overwrite_manual: bool = False,
    engine: str = "baseline",
) -> dict:
    """Process an image, preserving reviewed/manual work unless explicitly rerun.

    GUI callers defer expensive overlays until export. Full image filenames in
    state/overlay paths distinguish e.g. plate.jpg from plate.png.
    """
    # Validate before legacy migration or any other persistence. Direct callers
    # and older CLI behavior keep the unchanged baseline unless opting in.
    if engine not in ("baseline", "component_watershed_v1"):
        raise ValueError(f"unsupported built-in counting engine: {engine}")
    params = params or SegmentParams()
    det_path = run_dir / "detections" / f"{img_path.name}.json"
    overlay_path = run_dir / "overlays" / f"{img_path.name}.png"
    existing = _load_detections(det_path)
    # Read old workspaces without assigning one legacy state to two images.
    if existing is None:
        legacy = run_dir / "detections" / f"{img_path.stem}.json"
        same_stem = ([p for p in img_path.parent.iterdir()
                      if p.is_file() and p.stem == img_path.stem
                      and p.suffix.lower() in {".jpg", ".jpeg", ".png", ".tif", ".tiff"}]
                     if legacy.exists() else [])
        if len(same_stem) == 1:
            existing = _load_detections(legacy)
            if existing is not None:
                atomic_write_json(det_path, existing)
                legacy.unlink(missing_ok=True)

    preserve = bool(existing and (
        (existing.get("mode") == "manual" and not overwrite_manual)
        or ((existing.get("reviewed") or existing.get("counted")) and not force)
    ))
    img_bgr = None
    if not preserve or write_overlay:
        img_bgr = cv2.imdecode(np.fromfile(str(img_path), dtype=np.uint8), cv2.IMREAD_COLOR)
        if img_bgr is None:
            raise RuntimeError(f"failed to read image: {img_path.name}")

    if preserve:
        plate = PlateCircle(**existing["plate"])
        dets = [Detection(**d) for d in existing["detections"]]
        machine_count_initial = existing.get(
            "machine_count_initial", sum(1 for d in dets if d.source == "cv")
        )
    else:
        if plate_override is not None:
            plate = plate_override
        elif existing and existing.get("plate_manual"):
            plate = PlateCircle(**existing["plate"])
        else:
            plate = detect_plate(img_bgr)
        if engine == "component_watershed_v1":
            from .experiments.segmentation import CandidateConfig, segment_candidate
            dets, diagnostics = segment_candidate(img_bgr, plate, params, CandidateConfig())
        else:
            dets, diagnostics = segment(img_bgr, plate, params)
        machine_count_initial = len(dets)
        height, width = img_bgr.shape[:2]
        _save_detections(
            det_path, dets, plate, diagnostics, False, params, machine_count_initial,
            previous=existing, image_size={"width": width, "height": height}, engine=engine,
        )

    if write_overlay:
        overlay_path.parent.mkdir(parents=True, exist_ok=True)
        overlay_img = render(img_bgr, dets, plate)
        ok, encoded = cv2.imencode(".png", overlay_img, [cv2.IMWRITE_PNG_COMPRESSION, 1])
        if not ok:
            raise RuntimeError(f"failed to encode overlay: {img_path.name}")
        encoded.tofile(str(overlay_path))

    cv_remaining = sum(1 for d in dets if d.source == "cv")
    return {
        "filename": img_path.name,
        "total_count": len(dets),
        "machine_count": machine_count_initial,
        "n_removed": machine_count_initial - cv_remaining,
        "n_added": sum(1 for d in dets if d.source == "manual"),
        "notes": existing.get("notes", "") if existing else "",
    }


def batch(
    image_paths: Iterable[Path],
    run_dir: Path,
    params: SegmentParams = None,
    force: bool = False,
) -> Path:
    """Process many images; writes results.csv to run_dir and returns its path."""
    rows = []
    image_paths = list(image_paths)
    run_dir.mkdir(parents=True, exist_ok=True)
    for i, p in enumerate(image_paths, 1):
        try:
            row = process_image(p, run_dir, params=params, force=force)
        except Exception as exc:  # noqa: BLE001
            row = {"filename": p.name, "error": str(exc), "total_count": ""}
        rows.append(row)
        print(f"[{i}/{len(image_paths)}] {p.name} → cfu={row.get('total_count')}")
    out_csv = run_dir / "results.csv"
    pd.DataFrame(rows).to_csv(out_csv, index=False)
    return out_csv
