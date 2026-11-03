"""Component watershed for controlled comparison and the local internal UI.

The default candidate changes relative peak thresholding from one global image
maximum to each disconnected foreground component. It does not change the HSV,
area, circularity, eccentricity, or solidity gates in SegmentParams. Disconnected
small objects can consequently receive a seed even beside a much larger object;
this can recover colonies or admit noise, so it is not an accuracy guarantee.

Optional scale adaptation uses a declared reference plate radius of 800 pixels
(a 1600-pixel dish diameter): the baseline 5/9-pixel morphology kernels and the
configured peak spacing apply at that radius. Other radii scale those lengths
linearly; kernels are rounded to the nearest positive odd integer and spacing
to the nearest positive integer. This reference is a reproducible experiment
setting, not a calibration fitted to the user's photographs. Both scale options
are OFF by default. The shipped wecfu.segment implementation is unchanged.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import math
from typing import Any

import cv2
import numpy as np
from scipy import ndimage as ndi
from skimage.feature import peak_local_max
from skimage.segmentation import watershed

from ..plate import PlateCircle
from ..segment import (
    Detection, SegmentParams, _region_stats, _watershed_split, _white_colony_mask,
)

ALGORITHM = "component_watershed_v1"


@dataclass(frozen=True)
class CandidateConfig:
    algorithm: str = ALGORITHM
    component_seeding: bool = True
    scale_morphology: bool = False
    scale_seeding: bool = False
    reference_plate_radius_px: float = 800.0

    def __post_init__(self) -> None:
        if self.algorithm != ALGORITHM:
            raise ValueError(f"algorithm must be {ALGORITHM!r}")
        for name in ("component_seeding", "scale_morphology", "scale_seeding"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be a boolean")
        radius = self.reference_plate_radius_px
        if isinstance(radius, bool) or not isinstance(radius, (int, float)) or not math.isfinite(radius) or radius <= 0:
            raise ValueError("reference_plate_radius_px must be finite and positive")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> "CandidateConfig":
        if not isinstance(values, dict):
            raise ValueError("candidate configuration must be an object")
        return cls(**values)


def _scaled_odd(size: int, scale: float) -> int:
    return max(1, 2 * int(round((size * scale - 1) / 2)) + 1)


def _effective_lengths(plate: PlateCircle, params: SegmentParams, config: CandidateConfig) -> dict:
    scale = plate.r / config.reference_plate_radius_px
    return {
        "plate_scale": scale,
        "opening_kernel_px": _scaled_odd(5, scale) if config.scale_morphology else 5,
        "closing_kernel_px": _scaled_odd(9, scale) if config.scale_morphology else 9,
        "peak_min_distance_px": max(1, int(round(params.peak_min_distance * scale)))
        if config.scale_seeding else params.peak_min_distance,
    }


def _candidate_mask(img_bgr: np.ndarray, plate_mask: np.ndarray,
                    params: SegmentParams, opening: int, closing: int) -> np.ndarray:
    if opening == 5 and closing == 9:
        return _white_colony_mask(img_bgr, plate_mask, params.min_value, params.max_saturation)
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    white = (hsv[..., 2] >= params.min_value) & (hsv[..., 1] <= params.max_saturation)
    bw = (plate_mask & white).astype(np.uint8) * 255
    for operation, size in ((cv2.MORPH_OPEN, opening), (cv2.MORPH_CLOSE, closing)):
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))
        bw = cv2.morphologyEx(bw, operation, kernel)
    return bw


def _component_watershed_split(bw: np.ndarray, params: SegmentParams) -> tuple[np.ndarray, int]:
    """Preserve the two-value segmentation interface for existing callers."""
    labels, count, _ = _component_watershed_split_with_distance(bw, params)
    return labels, count


def _component_watershed_split_with_distance(
    bw: np.ndarray, params: SegmentParams,
) -> tuple[np.ndarray, int, np.ndarray | None]:
    """Seed each 4-connected island independently, then watershed the whole mask.

    Distance values use the full image, so an island's bounding box introduces
    neither an artificial border nor a changed distance transform. Peak search
    explicitly preserves baseline full-image border exclusion; local crop edges
    do not exclude small islands' peaks. Other islands inside an enclosing
    bounding box are masked out before computing its relative threshold.

    Return the existing float64 distance image for callers that also need seed
    locations. An empty foreground has no distance image and returns None.
    """
    foreground = bw > 0
    components, n_components = ndi.label(foreground)
    if n_components == 0:
        return np.zeros(bw.shape, dtype=np.int32), 0, None
    distance = ndi.distance_transform_edt(foreground)
    markers = np.zeros(bw.shape, dtype=np.int32)
    height, width = bw.shape
    spacing = params.peak_min_distance
    next_marker = 1
    for component_id, bounds in enumerate(ndi.find_objects(components), 1):
        if bounds is None:
            continue
        ys, xs = bounds
        member = components[bounds] == component_id
        local_distance = np.where(member, distance[bounds], 0)
        yy = np.arange(ys.start, ys.stop)[:, None]
        xx = np.arange(xs.start, xs.stop)[None, :]
        eligible = member & (yy >= spacing) & (yy < height - spacing) & (xx >= spacing) & (xx < width - spacing)
        if not eligible.any():
            continue
        coords = peak_local_max(
            local_distance,
            min_distance=spacing,
            threshold_rel=params.peak_rel_threshold,
            labels=eligible.astype(np.int32),
            exclude_border=False,
        )
        for y, x in coords:
            markers[y + ys.start, x + xs.start] = next_marker
            next_marker += 1
    # Preserve the baseline treatment of adjacent seed pixels.
    markers = ndi.label(markers > 0)[0]
    labels = watershed(-distance, markers, mask=foreground)
    return labels, int(labels.max(initial=0)), distance


def _cropped_region_stats(labels: np.ndarray, label: int, bounds: tuple[slice, slice]) -> dict:
    """Equivalent contour geometry on the label bbox, restored to image pixels."""
    stats = _region_stats(labels[bounds] == label)
    if stats:
        stats["cx"] += bounds[1].start
        stats["cy"] += bounds[0].start
    return stats


def segment_candidate(
    img_bgr: np.ndarray,
    plate: PlateCircle,
    params: SegmentParams | None = None,
    config: CandidateConfig | None = None,
) -> tuple[list[Detection], dict]:
    """Return detections/diagnostics without writing files.

    Diagnostics serialize all candidate switches and their effective pixel
    lengths. With component and scale switches disabled, this uses baseline
    mask/seeding and the same acceptance gates, with cropped geometry only.
    """
    params = params or SegmentParams()
    config = config or CandidateConfig()
    if not isinstance(config, CandidateConfig):
        raise TypeError("config must be a CandidateConfig")
    if img_bgr.ndim != 3 or img_bgr.shape[2] != 3 or img_bgr.shape[0] == 0 or img_bgr.shape[1] == 0:
        raise ValueError("img_bgr must be a nonempty H×W×3 BGR image")
    if not all(math.isfinite(v) for v in (plate.cx, plate.cy, plate.r)) or plate.r <= 0:
        raise ValueError("plate must have finite coordinates and a positive radius")
    effective = _effective_lengths(plate, params, config)
    effective_params = replace(params, peak_min_distance=effective["peak_min_distance_px"])
    height, width = img_bgr.shape[:2]
    mask = plate.mask((height, width), shrink=params.plate_inset)
    bw = _candidate_mask(img_bgr, mask, params, effective["opening_kernel_px"], effective["closing_kernel_px"])
    split = _component_watershed_split if config.component_seeding else _watershed_split
    labels, n_labels = split(bw, effective_params)

    plate_area = np.pi * (plate.r * params.plate_inset) ** 2
    min_area, max_area = params.min_area_frac * plate_area, params.max_area_frac * plate_area
    detections = []
    bad_shape = 0
    # One label scan replaces n full-frame masks and contour scans.
    for label, bounds in enumerate(ndi.find_objects(labels), 1):
        if bounds is None:
            continue
        stats = _cropped_region_stats(labels, label, bounds)
        if not stats or stats["area"] < min_area or stats["area"] > max_area:
            continue
        dx, dy = stats["cx"] - plate.cx, stats["cy"] - plate.cy
        if dx * dx + dy * dy > (plate.r * params.plate_inset) ** 2:
            continue
        if (stats["circularity"] < params.min_circularity
                or stats["solidity"] < params.min_solidity
                or stats["eccentricity"] > params.max_eccentricity):
            bad_shape += 1
            continue
        detections.append(Detection(
            id=len(detections) + 1, cx=stats["cx"], cy=stats["cy"], r=stats["r"],
            score=stats["circularity"] * stats["solidity"],
        ))
    foreground_fraction = float((bw > 0).sum()) / float(mask.sum() or 1)
    return detections, {
        "n_raw_regions": n_labels,
        "n_rejected_shape": bad_shape,
        "foreground_fraction": foreground_fraction,
        "mean_radius_px": float(np.mean([d.r for d in detections])) if detections else 0.0,
        "low_confidence": bool(foreground_fraction > 0.15 or (
            bad_shape >= max(3, len(detections)) and foreground_fraction > 0.05)),
        "candidate_config": config.to_dict(),
        "effective_lengths": effective,
    }
