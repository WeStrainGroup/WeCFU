"""Layer 2 — Meta Segment Anything fallback for dense plates.

Lazily imports torch + segment_anything so the base install stays slim.
Default checkpoint: ViT-B (sam_vit_b_01ec64.pth ~358 MB). The user is expected
to download it once and point CFU_SAM_CHECKPOINT at it (or place it at
~/.cache/wecfu/sam_vit_b.pth).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List

import cv2
import numpy as np

from .plate import PlateCircle
from .segment import Detection


def _default_checkpoint() -> Path:
    return Path(
        os.environ.get(
            "CFU_SAM_CHECKPOINT",
            str(Path.home() / ".cache" / "wecfu" / "sam_vit_b.pth"),
        )
    )


def _ensure_available() -> None:
    try:
        import torch  # noqa: F401
        import segment_anything  # noqa: F401
    except ImportError as e:  # noqa: F841
        raise RuntimeError(
            "SAM fallback requires extras. Install with:\n"
            "    pip install segment-anything torch\n"
            "Then download the ViT-B checkpoint:\n"
            "    mkdir -p ~/.cache/wecfu && curl -L "
            "https://dl.fbaipublicfiles.com/segment_anything/sam_vit_b_01ec64.pth "
            "-o ~/.cache/wecfu/sam_vit_b.pth"
        )
    ckpt = _default_checkpoint()
    if not ckpt.exists():
        raise RuntimeError(
            f"SAM checkpoint missing: {ckpt}\n"
            "Download with:\n"
            "    mkdir -p ~/.cache/wecfu && curl -L "
            "https://dl.fbaipublicfiles.com/segment_anything/sam_vit_b_01ec64.pth "
            f"-o {ckpt}"
        )


def sam_segment(
    img_bgr: np.ndarray,
    plate: PlateCircle,
    plate_inset: float = 0.92,
    min_area_frac: float = 0.00005,
    max_area_frac: float = 0.05,
    min_circularity: float = 0.55,
) -> List[Detection]:
    """Run SAM auto-mask generator and filter to colony-like circular masks."""
    _ensure_available()
    import torch
    from segment_anything import SamAutomaticMaskGenerator, sam_model_registry

    device = (
        "mps"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available()
        else "cpu"
    )
    sam = sam_model_registry["vit_b"](checkpoint=str(_default_checkpoint())).to(device)

    h, w = img_bgr.shape[:2]
    plate_mask = plate.mask((h, w), shrink=plate_inset)
    plate_area = np.pi * (plate.r * plate_inset) ** 2
    min_area = min_area_frac * plate_area
    max_area = max_area_frac * plate_area

    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    gen = SamAutomaticMaskGenerator(
        sam,
        points_per_side=48,
        min_mask_region_area=int(min_area),
    )
    masks = gen.generate(img_rgb)

    detections: List[Detection] = []
    next_id = 1
    for m in masks:
        seg = m["segmentation"] & plate_mask
        area = seg.sum()
        if area < min_area or area > max_area:
            continue
        contours, _ = cv2.findContours(
            seg.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE
        )
        if not contours:
            continue
        c = max(contours, key=cv2.contourArea)
        perim = cv2.arcLength(c, True)
        if perim <= 0:
            continue
        circularity = 4 * np.pi * cv2.contourArea(c) / (perim * perim)
        if circularity < min_circularity:
            continue
        (cx, cy), r = cv2.minEnclosingCircle(c)
        detections.append(
            Detection(
                id=next_id,
                cx=float(cx),
                cy=float(cy),
                r=float(r),
                score=float(circularity * m.get("stability_score", 1.0)),
                source="sam",
            )
        )
        next_id += 1
    return detections
