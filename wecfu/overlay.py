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

_COLOR_CV = (150, 131, 183)     # #B78396 in BGR, 90% opacity
_COLOR_MANUAL = (166, 149, 117) # #7595A6 in BGR, 90% opacity
_BG = (32, 32, 32)               # neutral grey outside the plate
_PAD = 24                        # padding around the plate when cropping


def _color(d: Detection) -> tuple:
    if d.source == "manual":
        return _COLOR_MANUAL
    return _COLOR_CV


def _draw_mark(
    out: np.ndarray, center: tuple[int, int], radius: int, color: tuple,
) -> None:
    """Keep the original geometry and a common solid stroke for both sources."""
    cv2.circle(out, center, radius, color, 3, cv2.LINE_AA)


def _crop_to_plate(
    img: np.ndarray, plate: PlateCircle, pad: int = _PAD
) -> Tuple[np.ndarray, int, int]:
    """Mask outside the plate to neutral grey and crop to plate bbox + pad."""
    h, w = img.shape[:2]
    x0 = max(0, int(plate.cx - plate.r - pad))
    y0 = max(0, int(plate.cy - plate.r - pad))
    x1 = min(w, int(np.ceil(plate.cx + plate.r + pad)))
    y1 = min(h, int(np.ceil(plate.cy + plate.r + pad)))
    # Work only on the exported region. Large camera photos otherwise allocate
    # a full-frame floating point distance image just to discard its margins.
    masked = img[y0:y1, x0:x1].copy()
    yy, xx = np.ogrid[y0:y1, x0:x1]
    inside = (xx - plate.cx) ** 2 + (yy - plate.cy) ** 2 <= plate.r * plate.r
    masked[~inside] = _BG
    return masked, x0, y0


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

    # One temporary image per source class, not per mark. An untouched layer
    # pixel equals out exactly, so alpha compositing preserves the photo there.
    # Manual marks are composited last when the two source classes overlap.
    for manual, color, alpha in ((False, _COLOR_CV, 0.9),
                                 (True, _COLOR_MANUAL, 0.9)):
        members = [d for d in detections if (d.source == "manual") == manual]
        if not members:
            continue
        layer = out.copy()
        for d in members:
            cx_d = int(d.cx - ox)
            cy_d = int(d.cy - oy)
            _draw_mark(layer, (cx_d, cy_d), max(int(d.r), 4), color)
            label_pt = (int(cx_d + d.r + 2), int(cy_d - 2))
            cv2.putText(
                layer,
                str(d.id),
                label_pt,
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                color,
                1,
                cv2.LINE_AA,
            )
        cv2.addWeighted(layer, alpha, out, 1 - alpha, 0, dst=out)
        del layer

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
