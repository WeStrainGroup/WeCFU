"""Layer 1 — classical CV pipeline for colony segmentation.

Input:  BGR image + PlateCircle.
Output: list[Detection]  (per-colony center, radius, source='cv', accepted=True).

Tunable parameters live in SegmentParams; the GUI exposes them as sliders and
re-runs this module for the current plate.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import List, Tuple

import cv2
import numpy as np
from scipy import ndimage as ndi
from skimage.feature import peak_local_max
from skimage.segmentation import watershed

from .plate import PlateCircle


@dataclass
class SegmentParams:
    # Fraction of plate radius used as a shrunken ROI (avoids glare rim).
    plate_inset: float = 0.82
    # Colony area bounds as fraction of plate area.
    min_area_frac: float = 0.00010
    max_area_frac: float = 0.05
    # Shape filters.
    min_circularity: float = 0.55
    max_eccentricity: float = 0.88
    min_solidity: float = 0.80
    # Watershed seed selectivity (higher = fewer seeds = less splitting).
    peak_min_distance: int = 15
    peak_rel_threshold: float = 0.50
    # White-colony gate (HSV).
    min_value: int = 200         # V channel — colonies are bright
    max_saturation: int = 60     # S channel — colonies are near-white


@dataclass
class Detection:
    id: int
    cx: float
    cy: float
    r: float
    score: float = 1.0
    accepted: bool = True
    source: str = "cv"  # "cv" (machine-detected) | "manual" (user-added)

    def asdict(self) -> dict:
        return asdict(self)


def _white_colony_mask(
    img_bgr: np.ndarray,
    plate_mask: np.ndarray,
    min_value: int,
    max_saturation: int,
) -> np.ndarray:
    """Pixels that look like white/cream colonies: bright AND near-white."""
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    s = hsv[:, :, 1]
    v = hsv[:, :, 2]

    white = (v >= min_value) & (s <= max_saturation)
    bw = (plate_mask & white).astype(np.uint8) * 255

    # Clean specks and fill small holes inside colonies.
    open_k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    bw = cv2.morphologyEx(bw, cv2.MORPH_OPEN, open_k)
    close_k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    bw = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, close_k)
    return bw


def _watershed_split(
    bw: np.ndarray, params: SegmentParams
) -> Tuple[np.ndarray, int]:
    distance = ndi.distance_transform_edt(bw > 0)
    coords = peak_local_max(
        distance,
        min_distance=params.peak_min_distance,
        threshold_rel=params.peak_rel_threshold,
        labels=(bw > 0).astype(np.int32),
    )
    markers = np.zeros(bw.shape, dtype=np.int32)
    for i, (y, x) in enumerate(coords, start=1):
        markers[y, x] = i
    markers = ndi.label(markers > 0)[0]  # connected blobs of seeds → unique IDs
    labels = watershed(-distance, markers, mask=(bw > 0))
    return labels, int(labels.max())


def _region_stats(region_mask: np.ndarray) -> dict:
    """Compute the shape descriptors used by the filter."""
    contours, _ = cv2.findContours(
        region_mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE
    )
    if not contours:
        return {}
    c = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(c)
    if area <= 0:
        return {}
    perim = cv2.arcLength(c, True)
    if perim <= 0:
        return {}
    circularity = 4 * np.pi * area / (perim * perim)
    (x, y), r_enc = cv2.minEnclosingCircle(c)
    hull = cv2.convexHull(c)
    hull_area = cv2.contourArea(hull) or area
    solidity = area / hull_area
    if len(c) >= 5:
        (_, _), (MA, ma), _ = cv2.fitEllipse(c)
        if MA == 0:
            ecc = 1.0
        else:
            ecc = np.sqrt(1 - (min(MA, ma) / max(MA, ma)) ** 2)
    else:
        ecc = 0.0
    return {
        "area": area,
        "circularity": circularity,
        "solidity": solidity,
        "eccentricity": ecc,
        "cx": float(x),
        "cy": float(y),
        "r": float(r_enc),
    }


def segment(
    img_bgr: np.ndarray,
    plate: PlateCircle,
    params: SegmentParams = None,
) -> Tuple[List[Detection], dict]:
    """Run the Layer 1 pipeline.

    Returns (detections, diagnostics). `diagnostics` contains aggregate signals
    used by the UI to flag low-confidence results.
    """
    params = params or SegmentParams()
    h, w = img_bgr.shape[:2]
    mask = plate.mask((h, w), shrink=params.plate_inset)
    plate_area = np.pi * (plate.r * params.plate_inset) ** 2
    min_area = params.min_area_frac * plate_area
    max_area = params.max_area_frac * plate_area

    bw = _white_colony_mask(
        img_bgr,
        mask,
        params.min_value,
        params.max_saturation,
    )
    labels, n_labels = _watershed_split(bw, params)

    detections: List[Detection] = []
    next_id = 1
    bad_shape = 0
    for lbl in range(1, n_labels + 1):
        region = labels == lbl
        if not region.any():
            continue
        stats = _region_stats(region)
        if not stats:
            continue
        if stats["area"] < min_area or stats["area"] > max_area:
            continue
        # Bound by plate inset – the contour center must be inside.
        dx = stats["cx"] - plate.cx
        dy = stats["cy"] - plate.cy
        if dx * dx + dy * dy > (plate.r * params.plate_inset) ** 2:
            continue
        if (
            stats["circularity"] < params.min_circularity
            or stats["solidity"] < params.min_solidity
            or stats["eccentricity"] > params.max_eccentricity
        ):
            bad_shape += 1
            continue
        detections.append(
            Detection(
                id=next_id,
                cx=stats["cx"],
                cy=stats["cy"],
                r=stats["r"],
                score=stats["circularity"] * stats["solidity"],
            )
        )
        next_id += 1

    radii = [d.r for d in detections]
    mean_r = float(np.mean(radii)) if radii else 0.0

    # Low-confidence heuristic: many regions rejected for shape AND the
    # foreground covers a large fraction of the plate (suggests confluent growth).
    fg_frac = float((bw > 0).sum()) / float(mask.sum() or 1)
    low_confidence = (
        fg_frac > 0.15
        or (bad_shape >= max(3, len(detections)) and fg_frac > 0.05)
    )

    return detections, {
        "n_raw_regions": n_labels,
        "n_rejected_shape": bad_shape,
        "foreground_fraction": fg_frac,
        "mean_radius_px": mean_r,
        "low_confidence": bool(low_confidence),
    }
