"""Orchestrate plate detection → segmentation → persistence.

The pipeline writes three artifacts per image:
    runs/<run>/detections/<stem>.json   editable detection state
    runs/<run>/overlays/<stem>.png      annotated review image
And one aggregate:
    runs/<run>/results.csv              one row per image with counts + metadata
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Iterable, List, Optional

import cv2
import numpy as np
import pandas as pd

from .overlay import render
from .plate import PlateCircle, detect_plate
from .segment import Detection, SegmentParams, segment


def _load_detections(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _save_detections(
    path: Path,
    detections: List[Detection],
    plate: PlateCircle,
    diagnostics: dict,
    reviewed: bool,
    method: str,
    params: SegmentParams,
) -> None:
    payload = {
        "plate": {"cx": plate.cx, "cy": plate.cy, "r": plate.r},
        "detections": [d.asdict() for d in detections],
        "diagnostics": diagnostics,
        "reviewed": reviewed,
        "method": method,
        "params": asdict(params),
    }
    path.write_text(json.dumps(payload, indent=2))


def process_image(
    img_path: Path,
    run_dir: Path,
    params: SegmentParams = None,
    force: bool = False,
) -> dict:
    """Process one image; returns a dict suitable for the results.csv row."""
    params = params or SegmentParams()
    stem = img_path.stem
    det_path = run_dir / "detections" / f"{stem}.json"
    overlay_path = run_dir / "overlays" / f"{stem}.png"
    det_path.parent.mkdir(parents=True, exist_ok=True)
    overlay_path.parent.mkdir(parents=True, exist_ok=True)

    img_bgr = cv2.imdecode(np.fromfile(str(img_path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if img_bgr is None:
        raise RuntimeError(f"failed to read image: {img_path}")

    existing = None if force else _load_detections(det_path)
    if existing and existing.get("reviewed"):
        # Preserve user edits.
        plate = PlateCircle(**existing["plate"])
        dets = [Detection(**d) for d in existing["detections"]]
        diagnostics = existing.get("diagnostics", {})
        method = existing.get("method", "cv")
    else:
        plate = detect_plate(img_bgr)
        dets, diagnostics = segment(img_bgr, plate, params)
        method = "cv"
        _save_detections(det_path, dets, plate, diagnostics, False, method, params)

    overlay_img = render(img_bgr, dets, plate)
    cv2.imwrite(str(overlay_path), overlay_img)

    row = {
        "filename": img_path.name,
        "cfu_count": len(dets),
        "n_manual": sum(1 for d in dets if d.source == "manual"),
        "low_confidence": diagnostics.get("low_confidence", False),
        "notes": existing.get("notes", "") if existing else "",
    }
    return row


def batch(
    image_paths: Iterable[Path],
    run_dir: Path,
    params: SegmentParams = None,
    force: bool = False,
) -> Path:
    """Process many images; writes results.csv to run_dir and returns its path."""
    rows = []
    image_paths = list(image_paths)
    for i, p in enumerate(image_paths, 1):
        try:
            row = process_image(p, run_dir, params=params, force=force)
        except Exception as exc:  # noqa: BLE001
            row = {
                "filename": p.name,
                "error": str(exc),
                "cfu_count": "",
            }
        rows.append(row)
        print(f"[{i}/{len(image_paths)}] {p.name} → cfu={row.get('cfu_count')}")
    df = pd.DataFrame(rows)
    out_csv = run_dir / "results.csv"
    df.to_csv(out_csv, index=False)
    return out_csv
