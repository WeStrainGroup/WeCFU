"""Render an annotated review image: numbered circles over the original photo.

The exported overlay is cropped to a tight square around the plate and pixels
outside the plate circle are filled with a neutral grey so the dark table
background doesn't compete with the colonies.
"""

from __future__ import annotations

from typing import Iterable, Tuple

import cv2
import numpy as np

from .plate import PlateCircle
from .segment import Detection

_COLOR_CV = (239, 159, 74)       # blue   — machine-detected (BGR)
_COLOR_MANUAL = (84, 212, 134)   # green  — manually added (BGR)
_BG = (32, 32, 32)               # neutral grey outside the plate
_PAD = 24                        # padding around the plate when cropping


def _color(d: Detection) -> tuple:
    if d.source == "manual":
        return _COLOR_MANUAL
    return _COLOR_CV


def _crop_to_plate(
    img: np.ndarray, plate: PlateCircle, pad: int = _PAD
) -> Tuple[np.ndarray, int, int]:
    """Mask outside the plate to neutral grey and crop to plate bbox + pad."""
    h, w = img.shape[:2]
    yy, xx = np.ogrid[:h, :w]
    inside = (xx - plate.cx) ** 2 + (yy - plate.cy) ** 2 <= plate.r * plate.r
    masked = img.copy()
    masked[~inside] = _BG

    x0 = max(0, int(plate.cx - plate.r - pad))
    y0 = max(0, int(plate.cy - plate.r - pad))
    x1 = min(w, int(plate.cx + plate.r + pad))
    y1 = min(h, int(plate.cy + plate.r + pad))
    return masked[y0:y1, x0:x1], x0, y0


def render(
    img_bgr: np.ndarray,
    detections: Iterable[Detection],
    plate: PlateCircle,
    crop: bool = True,
    show_plate: bool = True,
) -> np.ndarray:
    """Draw numbered circles. If `crop`, mask outside the plate and tight-crop."""
    detections = list(detections)
    if crop:
        out, ox, oy = _crop_to_plate(img_bgr, plate)
    else:
        out = img_bgr.copy()
        ox = oy = 0

    if show_plate:
        cv2.circle(
            out,
            (int(plate.cx - ox), int(plate.cy - oy)),
            int(plate.r),
            (170, 170, 170),
            2,
        )

    for d in detections:
        color = _color(d)
        cx_d = int(d.cx - ox)
        cy_d = int(d.cy - oy)
        cv2.circle(out, (cx_d, cy_d), max(int(d.r), 4), color, 2)
        label_pt = (int(cx_d + d.r + 2), int(cy_d - 2))
        cv2.putText(
            out,
            str(d.id),
            label_pt,
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            color,
            1,
            cv2.LINE_AA,
        )

    banner = f"CFU={len(detections)}"
    cv2.rectangle(out, (10, 10), (10 + 14 * len(banner), 44), (0, 0, 0), -1)
    cv2.putText(
        out,
        banner,
        (16, 36),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.9,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )
    return out
