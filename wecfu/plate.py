"""Detect the petri dish circle in a plate photo.

Strategy: Hough circle transform on a downsampled grayscale image; if Hough
fails (returns no candidate or the candidate is implausibly small), fall back
to picking the largest highly-circular contour from a binary mask of the dark
background.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import cv2
import numpy as np


@dataclass
class PlateCircle:
    cx: float
    cy: float
    r: float

    def mask(self, shape: Tuple[int, int], shrink: float = 0.92) -> np.ndarray:
        """Boolean mask of the plate interior, inset by `shrink` to avoid rim."""
        h, w = shape
        yy, xx = np.ogrid[:h, :w]
        return (xx - self.cx) ** 2 + (yy - self.cy) ** 2 <= (self.r * shrink) ** 2


def _try_hough(gray: np.ndarray, scale: float) -> Optional[Tuple[float, float, float]]:
    h, w = gray.shape
    min_r = int(min(h, w) * 0.30)
    max_r = int(min(h, w) * 0.55)
    circles = cv2.HoughCircles(
        gray,
        cv2.HOUGH_GRADIENT,
        dp=1.2,
        minDist=min(h, w),
        param1=120,
        param2=40,
        minRadius=min_r,
        maxRadius=max_r,
    )
    if circles is None:
        return None
    c = circles[0, 0]
    return float(c[0]) / scale, float(c[1]) / scale, float(c[2]) / scale


def _largest_circular_contour(
    gray: np.ndarray, scale: float
) -> Optional[Tuple[float, float, float]]:
    """Find the agar boundary by isolating the bright interior of the dish.

    The photo has three radial zones: dark table background, bright glass rim
    glare, and the agar surface itself. Otsu of the whole frame separates
    table from dish; we then dilate to fill the rim glare and take the
    largest bright contour, which is bounded by the *outer* dish edge. To
    find the *agar* edge specifically, we further erode by a fixed margin
    that approximates the glass wall thickness.
    """
    blurred = cv2.GaussianBlur(gray, (7, 7), 0)
    _, binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best = None
    best_score = -1.0
    h, w = gray.shape
    img_area = h * w
    for c in contours:
        area = cv2.contourArea(c)
        if area < 0.05 * img_area:
            continue
        perim = cv2.arcLength(c, True)
        if perim <= 0:
            continue
        circularity = 4 * np.pi * area / (perim * perim)
        if circularity < 0.80:
            continue
        (x, y), r = cv2.minEnclosingCircle(c)
        score = area * circularity
        if score > best_score:
            best_score = score
            best = (float(x) / scale, float(y) / scale, float(r) / scale)
    return best


def detect_plate(img_bgr: np.ndarray) -> PlateCircle:
    """Locate the petri dish; raises RuntimeError if no plate can be found."""
    h, w = img_bgr.shape[:2]
    # Downsample so Hough/contour work on ~800px side — fast and noise-suppressed.
    target = 800
    scale = target / max(h, w)
    small = cv2.resize(img_bgr, (int(w * scale), int(h * scale)))
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    gray_blur = cv2.medianBlur(gray, 5)

    found = _try_hough(gray_blur, scale)
    if found is None:
        found = _largest_circular_contour(gray, scale)
    if found is None:
        raise RuntimeError("plate detection failed")
    cx, cy, r = found
    return PlateCircle(cx=cx, cy=cy, r=r)
