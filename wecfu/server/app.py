"""FastAPI backend for the private WeCFU interaction preview.

Workspaces remain local/per-session. All edit operations persist complete atomic
snapshots; preview rendering is deferred until requested or exported.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import shutil
import tempfile
import threading
import time
import zipfile
from copy import deepcopy
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import uuid4
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path
from typing import Callable, List, Literal, Optional
from urllib.parse import quote

import cv2
import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, StrictBool, StrictStr, model_validator
from starlette.background import BackgroundTask

from ..overlay import render
from ..pipeline import atomic_write_json, process_image
from ..plate import PlateCircle, detect_plate
from .. import reference as human_reference
from ..segment import Detection, SegmentParams, _white_colony_mask
from . import model_preview, review_queues, sam_runtime, fusion_runtime, fusion_runtime_v2
from . import viewed as viewed_metadata
from . import source_views

_IMG_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
_STATIC = Path(__file__).parent / "static"
WEB_MAX_BYTES = 400 * 1024 * 1024
WEB_MAX_IMAGES = 100
_LOCKS: dict[tuple, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()
_COMPONENT_ENGINE = "component_watershed_v1"
_SAM_FROZEN_ENGINE = "sam2_cv_frozen_v1"
_INTERNAL_DEFAULT_PARAMS = {"plate_inset": 0.95, "min_value": 200, "max_saturation": 100,
                            "min_circularity": 0.55, "min_area_frac": 0.0001, "peak_min_distance": 15}


class IngestBody(BaseModel):
    paths: List[str]
    batch: Optional[str] = None
    view: Literal["main", "blank", "back", "unknown"] = "unknown"


class CircleBody(BaseModel):
    cx: float = Field(ge=0, allow_inf_nan=False)
    cy: float = Field(ge=0, allow_inf_nan=False)
    r: float = Field(gt=0, allow_inf_nan=False)


class AddDetectionBody(CircleBody):
    pass


class DetectionBody(CircleBody):
    id: int = Field(ge=1)
    score: float = Field(default=1.0, ge=0, le=1, allow_inf_nan=False)
    accepted: bool = True
    source: Literal["cv", "manual"] = "cv"


class NotesBody(BaseModel):
    notes: str = Field(max_length=100000)


class ViewedBody(BaseModel):
    """UI display receipt only; never an editable-state or reference update."""
    model_config = {"extra": "forbid"}
    source_sha256: StrictStr = Field(pattern="^[0-9a-f]{64}$")


class SourceViewBody(ViewedBody):
    view: Literal["main", "blank", "back", "unknown"]


class ParamsBody(BaseModel):
    plate_inset: float = Field(default=SegmentParams.plate_inset, gt=0, le=1, allow_inf_nan=False)
    min_value: int = Field(default=SegmentParams.min_value, ge=0, le=255)
    max_saturation: int = Field(default=SegmentParams.max_saturation, ge=0, le=255)
    min_circularity: float = Field(default=SegmentParams.min_circularity, ge=0, le=1, allow_inf_nan=False)
    min_area_frac: float = Field(default=SegmentParams.min_area_frac, gt=0, le=0.05, allow_inf_nan=False)
    peak_min_distance: int = Field(default=SegmentParams.peak_min_distance, ge=1, le=500)


class InitializeBody(BaseModel):
    mode: Literal["manual", "auto"] = "manual"


class CountModelBody(BaseModel):
    model_config = {"extra": "forbid"}
    model_sha256: StrictStr = Field(pattern="^[0-9a-f]{64}$")
    image_sha256: StrictStr = Field(pattern="^[0-9a-f]{64}$")
    score_threshold: float = Field(allow_inf_nan=False)
    nms_threshold: float = Field(allow_inf_nan=False)
    plate_inset: float = Field(gt=0, le=1, allow_inf_nan=False)
    raw_count: int = Field(ge=0, strict=True)
    candidate_count: int = Field(ge=0, le=100000, strict=True)

    @model_validator(mode="after")
    def fixed_model_provenance(self):
        if (self.model_sha256 != model_preview.MODEL_SHA256 or
                self.score_threshold != model_preview.SCORE_THRESHOLD or
                self.nms_threshold != model_preview.NMS_THRESHOLD or self.candidate_count > self.raw_count):
            raise ValueError("invalid fixed CFUCounter provenance")
        return self


class ModelParamsBody(BaseModel):
    model_config = {"extra": "forbid"}
    plate_inset: float = Field(gt=0, le=1, allow_inf_nan=False)


class FrozenSamModelBody(BaseModel):
    """Provenance for imported, already computed SAM candidates; no inference API."""
    model_config = {"extra": "forbid"}
    method: Literal["sam_cv_seed_area0.05"]
    model_sha256: Literal["7402e0d864fa82708a20fbd15bc84245c2f26dff0eb43a4b5b93452deb34be69"]
    image_sha256: StrictStr = Field(pattern="^[0-9a-f]{64}$")
    predictions_sha256: StrictStr = Field(pattern="^[0-9a-f]{64}$")
    candidate_count: int = Field(ge=0, le=100000, strict=True)
    plate_inset: float = Field(gt=0, le=1, allow_inf_nan=False)


class LocalSamModelBody(BaseModel):
    """Fixed live SAM recipe provenance, separate from immutable review imports."""
    model_config = {"extra": "forbid"}
    model_sha256: Literal["7402e0d864fa82708a20fbd15bc84245c2f26dff0eb43a4b5b93452deb34be69"]
    image_sha256: StrictStr = Field(pattern="^[0-9a-f]{64}$")
    recipe_id: Literal["sam_cv_seed_area0.05_color160_edge095_v1"]
    plate_inset: Literal[0.95]
    raw_count: int = Field(ge=0, strict=True)
    candidate_count: int = Field(ge=0, le=20000, strict=True)

    @model_validator(mode="after")
    def matching_counts(self):
        if self.candidate_count > self.raw_count:
            raise ValueError("candidate count exceeds raw proposals")
        return self


class FixedSamParamsBody(BaseModel):
    model_config = {"extra": "forbid"}


class LocalFusionModelBody(BaseModel):
    model_config = {"extra": "forbid"}
    model_sha256: StrictStr = Field(pattern="^[0-9a-f]{64}$")
    filter_artifact_sha256: StrictStr = Field(pattern="^[0-9a-f]{64}$")
    sam_model_sha256: Literal["7402e0d864fa82708a20fbd15bc84245c2f26dff0eb43a4b5b93452deb34be69"]
    dino_model_sha256: Literal["af2e3769e6f1512f4dabb3043b6b4a5de97935549eaa843bfa3074728ce630ea"]
    detector_contract_sha256: StrictStr = Field(pattern="^[0-9a-f]{64}$")
    recipe_id: Literal["sam_dino_full88_residual12_threshold075_auto095_v1"]
    image_sha256: StrictStr = Field(pattern="^[0-9a-f]{64}$")
    plate_inset: Literal[0.95]
    automatic_plate: CircleBody
    raw_count: int = Field(ge=0, strict=True)
    candidate_count: int = Field(ge=0, le=20000, strict=True)
    d0_count: int = Field(ge=0, strict=True)
    supplemental_count: int = Field(ge=0, le=900, strict=True)
    raw_dino_count: int = Field(ge=0, le=900, strict=True)
    annotation_kind: Literal["SAM_D0_plus_box_derived_center_rings"]

    @model_validator(mode="after")
    def matching_counts(self):
        if (self.d0_count + self.supplemental_count != self.candidate_count or
                self.supplemental_count > self.raw_dino_count or self.candidate_count > self.raw_count):
            raise ValueError("invalid preserved D0 plus supplementary count provenance")
        return self


class LocalFusionV2ModelBody(LocalFusionModelBody):
    recipe_id: Literal["sam_dino_raw10_threshold075_auto095_v2"]
    source_view: Literal["main", "blank"]
    feature_projection: list[int]
    coordinate_method: Literal["raw_DINO_unchanged"]
    D0_exclusion_fraction: Literal[0.025]
    DINO_dedup_fraction: Literal[0.005]
    ROI_max_radial: Literal[0.95]

    @model_validator(mode="after")
    def fixed_projection(self):
        if self.feature_projection != [0,1,2,5,6,7,8,9,10,11]:
            raise ValueError("invalid fixed Fusion v2 feature projection")
        return self


def _fusion_model_body(engine):
    return LocalFusionV2ModelBody if engine == fusion_runtime_v2.ENGINE else LocalFusionModelBody


_FUSION_ENGINES = (fusion_runtime.ENGINE, fusion_runtime_v2.ENGINE)


class ModelPreviewBody(BaseModel):
    model_config = {"extra": "forbid"}
    engine: Literal["cfucounter_onnx_author_v1", "sam2_local_v1", "sam_dino_fusion_local_v1", "sam_dino_fusion_local_v2"]
    expected_revision: int = Field(ge=0, strict=True)
    expected_image_sha256: StrictStr = Field(pattern="^[0-9a-f]{64}$")
    model_params: ModelParamsBody | FixedSamParamsBody
    only_unrecognized: StrictBool = False

    @model_validator(mode="after")
    def fixed_engine_parameters(self):
        if self.engine in (sam_runtime.ENGINE, *_FUSION_ENGINES) and not isinstance(self.model_params, FixedSamParamsBody):
            raise ValueError("SAM2 uses a fixed recipe; model_params must be empty")
        if self.engine == model_preview.ENGINE and not isinstance(self.model_params, ModelParamsBody):
            raise ValueError("CFUCounter requires its saved ROI")
        return self


class ApplyModelPreviewBody(BaseModel):
    model_config = {"extra": "forbid"}
    candidate_id: StrictStr = Field(min_length=1, max_length=100)
    expected_revision: int = Field(ge=0, strict=True)
    expected_image_sha256: StrictStr = Field(pattern="^[0-9a-f]{64}$")
    replace_all: StrictBool
    request_id: StrictStr = Field(min_length=1, max_length=100, pattern="^[A-Za-z0-9_-]+$")
    only_unrecognized: StrictBool = False

    @model_validator(mode="after")
    def explicit_replacement(self):
        if self.replace_all is not True:
            raise ValueError("replace_all must be literal true to replace every current mark")
        return self


class RestoreModelPreviewBody(BaseModel):
    model_config = {"extra": "forbid"}
    recovery_id: StrictStr = Field(pattern="^[0-9a-f]{32}$")
    expected_revision: int = Field(ge=0, strict=True)
    expected_image_sha256: StrictStr = Field(pattern="^[0-9a-f]{64}$")
    replace_all: StrictBool

    @model_validator(mode="after")
    def explicit_replacement(self):
        if self.replace_all is not True:
            raise ValueError("replace_all must be literal true")
        return self


class StateBody(BaseModel):
    detections: list[DetectionBody] = Field(max_length=100000)
    plate: CircleBody
    mode: Literal["manual", "auto"]
    machine_count_initial: int = Field(ge=0)
    notes: str = Field(default="", max_length=100000)
    plate_manual: bool = False
    reviewed: bool = True
    params: Optional[ParamsBody] = None
    counted: Optional[bool] = None
    count_params: Optional[ParamsBody] = None
    count_engine: Optional[Literal["baseline", "component_watershed_v1", "cfucounter_onnx_author_v1", "sam2_cv_frozen_v1", "sam2_local_v1", "sam_dino_fusion_local_v1", "sam_dino_fusion_local_v2"]] = None
    count_model: Optional[CountModelBody | FrozenSamModelBody | LocalSamModelBody | LocalFusionModelBody | LocalFusionV2ModelBody] = None
    expected_revision: Optional[int] = Field(default=None, ge=0)

    @model_validator(mode="before")
    @classmethod
    def no_reference_attestations(cls, values):
        if isinstance(values, dict) and set(values) & {
            "verified", "human_confirmed", "annotator", "group_id", "reference", "reference_id", "review_scope",
        }:
            raise ValueError("human reference attestations require the separate reference endpoint")
        return values


class ReviewScopeBody(BaseModel):
    model_config = {"extra": "forbid"}
    colony_count_reviewed: StrictBool
    colony_center_points_reviewed: StrictBool
    plate_crop_reviewed: StrictBool = False

    @model_validator(mode="after")
    def explicit_review(self):
        human_reference.canonical_review_scope(_dump(self))
        return self


class ConfirmReferenceBody(BaseModel):
    expected_revision: int = Field(ge=0, strict=True)
    expected_image_sha256: StrictStr = Field(pattern="^[0-9a-f]{64}$")
    human_confirmed: StrictBool
    annotator: StrictStr = Field(min_length=1, max_length=80)
    group_id: Optional[StrictStr] = Field(default=None, max_length=200)
    review_scope: Optional[ReviewScopeBody] = None


class WithdrawReferenceBody(BaseModel):
    expected_reference_id: StrictStr = Field(min_length=1, max_length=100)


def _dump(model: BaseModel) -> dict:
    return model.model_dump() if hasattr(model, "model_dump") else model.dict()


def _component(value: str) -> str:
    if not value or value in {".", ".."} or any(c in value for c in ("/", "\\", "\0")):
        raise HTTPException(400, "invalid workspace path")
    return value


def _batch_dir(root: Path, batch: str, category: str = "inputs") -> Path:
    path = root / category / _component(batch)
    if path.is_symlink():
        raise HTTPException(400, "batch directory must not be a symlink")
    return path


def _lock(root: Path, batch: str, name: str = ""):
    key = (str(root.resolve()), _component(batch), _component(name) if name else "")
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.RLock())


def _default_batch(root: Path) -> str:
    inputs = root / "inputs"
    subdirs = [p for p in inputs.iterdir() if p.is_dir()] if inputs.exists() else []
    return max(subdirs, key=lambda p: p.stat().st_mtime).name if subdirs else time.strftime("session_%Y%m%d_%H%M%S")


def _image_for(root: Path, batch: str, name: str) -> Path:
    path = _batch_dir(root, batch) / _component(name)
    if not path.is_file() or path.suffix.lower() not in _IMG_EXTS:
        raise HTTPException(404, f"image not found: {name}")
    return path


def _images(root: Path, batch: str) -> list[Path]:
    directory = _batch_dir(root, batch)
    if not directory.is_dir():
        raise HTTPException(404, "batch not found")
    return sorted(p for p in directory.iterdir() if p.is_file() and p.suffix.lower() in _IMG_EXTS)


def _det_path(root: Path, batch: str, name: str) -> Path:
    return _batch_dir(root, batch, "runs") / "detections" / f"{_component(name)}.json"


def _overlay_path(root: Path, batch: str, name: str) -> Path:
    return _batch_dir(root, batch, "runs") / "overlays" / f"{_component(name)}.png"


def _reference_path(root: Path, batch: str, name: str) -> Path:
    return _batch_dir(root, batch, "runs") / "references" / f"{_component(name)}.json"


def _reference_status(root: Path, batch: str, name: str, *, strict_audit: bool = False) -> dict:
    """Called only by explicit reference routes, while the image lock is held."""
    image = _image_for(root, batch, name)
    state = _maybe_state(root, batch, name)
    document = human_reference.load_document(_reference_path(root, batch, name))
    if strict_audit and document is not None:
        current_id = document.get('current_reference_id')
        records = document['records']
        if (not isinstance(current_id, str) or not current_id.strip()
                or any(not isinstance(record, dict) for record in records)
                or sum(record.get('reference_id') == current_id for record in records) != 1):
            raise human_reference.ReferenceError("reference audit current pointer is missing, dangling or ambiguous")
    if document is None or document.get("withdrawn"):
        return human_reference.inspect_reference(document, state)
    try:
        snapshot = human_reference.read_source_snapshot(image)
    except (OSError, human_reference.ReferenceError):
        snapshot = None
    return human_reference.inspect_reference(document, state, snapshot)


def _load_state(root: Path, batch: str, name: str) -> dict:
    _image_for(root, batch, name)
    path = _det_path(root, batch, name)
    if not path.exists():
        legacy = path.with_name(f"{Path(name).stem}.json")
        if legacy.exists():
            same_stem = [p for p in _images(root, batch) if p.stem == Path(name).stem]
            if len(same_stem) == 1:
                state = _state_provenance_defaults(json.loads(legacy.read_text(encoding="utf-8")))
                _check_manual_only_state(root, batch, state)
                _check_assisted_state(root, batch, state)
                return state
        raise HTTPException(404, f"detections not run for {name}")
    state = _state_provenance_defaults(json.loads(path.read_text(encoding="utf-8")))
    _check_manual_only_state(root, batch, state)
    _check_assisted_state(root, batch, state)
    return state


def _manual_only(root: Path, batch: str) -> bool:
    return review_queues.annotation_mode_for_batch(root, batch) == 'manual_only'


def _require_machine_assistance(root: Path, batch: str) -> None:
    mode = review_queues.annotation_mode_for_batch(root, batch)
    if mode in ('manual_only', 'assisted_frozen'):
        raise HTTPException(403, "This review batch does not permit rerunning or replacing its initial machine predictions.")


def _require_unrecognized(root: Path, batch: str, name: str, state: dict) -> None:
    """Caller holds the image lock; browsing is not recognition or review."""
    reason = None
    if state.get("counted"):
        reason = "already_counted"
    elif state.get("counted") is not False:
        reason = "legacy_status_unknown"
    elif state.get("detections"):
        reason = "existing_marks"
    elif state.get("machine_count_initial", 0):
        reason = "machine_count_history"
    elif state.get("mode") == "manual":
        reason = "manual_mode"
    elif state.get("reviewed"):
        reason = "reviewed"
    elif str(state.get("notes") or ""):
        reason = "notes"
    elif state.get("plate_manual"):
        reason = "manual_plate"
    else:
        reference = _reference_path(root, batch, name)
        # A withdrawn/historical or dangling reference still protects this image.
        # No reference values are read and no reference status is changed here.
        if reference.exists() or reference.is_symlink():
            reason = "reference"
    if reason:
        raise HTTPException(409, f"only_unrecognized: {reason}; existing work was not replaced")


def _assisted(root: Path, batch: str) -> bool:
    return review_queues.annotation_mode_for_batch(root, batch) == 'assisted_frozen'


def _check_assisted_state(root: Path, batch: str, state: dict) -> None:
    if not _assisted(root, batch):
        return
    try:
        provenance = FrozenSamModelBody.model_validate(state.get('count_model'))
        valid = (state.get('mode') == 'auto' and state.get('counted') is True
                 and state.get('count_engine') == _SAM_FROZEN_ENGINE
                 and state.get('count_params') is None
                 and state.get('machine_count_initial') == provenance.candidate_count
                 and isinstance(state.get('detections'), list)
                 and all(isinstance(d, dict) and d.get('source') in ('cv', 'manual') for d in state['detections'])
                 and sum(d['source'] == 'cv' for d in state['detections']) <= provenance.candidate_count)
    except (ValueError, TypeError, AttributeError):
        valid = False
    if not valid:
        raise HTTPException(409, "Assisted review has invalid fixed machine provenance; no marks were changed.")


def _check_manual_only_state(root: Path, batch: str, state: dict) -> None:
    if not _manual_only(root, batch):
        return
    diagnostics = state.get('diagnostics', {})
    detections = state.get('detections', [])
    if (state.get('mode') != 'manual' or state.get('machine_count_initial', 0) != 0
            or state.get('counted', False) is not False
            or any(state.get(key) is not None for key in ('count_engine', 'count_model', 'count_params', '_model_preview_apply'))
            or not isinstance(diagnostics, dict) or diagnostics.get('algorithm') is not None
            or not isinstance(detections, list)
            or any(not isinstance(d, dict) or d.get('source') != 'manual' for d in detections)):
        raise HTTPException(409, "Manual-only batch contains machine or automatic state; repair the batch before reviewing. No marks were changed.")


def _state_provenance_defaults(state: dict) -> dict:
    # Compatibility is in-memory only; opening an old state never writes it.
    state.setdefault("count_engine", None if state.get("mode") == "manual" else "baseline")
    state.setdefault("count_model", None)
    return state


def _maybe_state(root: Path, batch: str, name: str) -> Optional[dict]:
    try:
        return _load_state(root, batch, name)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        return None


def _save_state(root: Path, batch: str, name: str, state: dict) -> None:
    _check_manual_only_state(root, batch, state)
    _check_assisted_state(root, batch, state)
    state["revision"] = state.get("revision", 0) + 1
    atomic_write_json(_det_path(root, batch, name), state)
    # Retire an unambiguous old filename once its replacement is durable. A
    # stale legacy file must not be inherited by a later same-stem import.
    legacy = _det_path(root, batch, name).with_name(f"{Path(name).stem}.json")
    if legacy.exists() and sum(p.stem == Path(name).stem for p in _images(root, batch)) == 1:
        legacy.unlink(missing_ok=True)


def _migrate_legacy_states(root: Path, batch: str) -> None:
    # Run before appending new files so a newly imported same-stem image cannot
    # inherit a previous image's old-style state.
    images = _images(root, batch)
    stem_counts = {}
    for image in images:
        stem_counts[image.stem] = stem_counts.get(image.stem, 0) + 1
    for image in images:
        with _lock(root, batch, image.name):
            target = _det_path(root, batch, image.name)
            if not target.exists():
                state = _maybe_state(root, batch, image.name)
                if state is not None:
                    atomic_write_json(target, state)
            if target.exists() and stem_counts[image.stem] == 1:
                target.with_name(f"{image.stem}.json").unlink(missing_ok=True)


@lru_cache(maxsize=3)
def _decode_image(path: str, modified: int, size: int) -> np.ndarray:
    image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise HTTPException(422, "image could not be decoded")
    return image


def _read_image(path: Path) -> np.ndarray:
    stat = path.stat()
    return _decode_image(str(path), stat.st_mtime_ns, stat.st_size)


@lru_cache(maxsize=8)
def _tiff_browser_preview(path: str, modified: int, size: int) -> bytes:
    """Browser-compatible view with the exact coordinates of the original TIFF."""
    pixels = _decode_image(path, modified, size)
    ok, encoded = cv2.imencode(".jpg", pixels, [cv2.IMWRITE_JPEG_QUALITY, 95])
    if not ok:
        raise HTTPException(500, "image preview encoding failed")
    return encoded.tobytes()


def _validate_circle(circle: CircleBody, width: int, height: int) -> None:
    if circle.cx > width or circle.cy > height or circle.r > math.hypot(width, height):
        raise HTTPException(422, "circle is outside image bounds")


def _render_key(path: Path, state: dict) -> str:
    stat = path.stat()
    content = ["marks-v7-morandi", str(path.resolve()), stat.st_mtime_ns, stat.st_size,
               state["plate"], state["detections"]]
    return hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _rerender(root: Path, batch: str, name: str, state: dict) -> None:
    path = _image_for(root, batch, name)
    key = _render_key(path, state)
    overlay = render(_read_image(path), [Detection(**d) for d in state["detections"]], PlateCircle(**state["plate"]), crop=True)
    out = _overlay_path(root, batch, name)
    out.parent.mkdir(parents=True, exist_ok=True)
    ok, data = cv2.imencode(".png", overlay, [cv2.IMWRITE_PNG_COMPRESSION, 1])
    if not ok:
        raise HTTPException(500, "overlay encoding failed")
    fd, temporary = tempfile.mkstemp(prefix=".overlay-", dir=out.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(temporary, out)
        atomic_write_json(out.with_suffix(".cache.json"), {"key": key})
    finally:
        Path(temporary).unlink(missing_ok=True)


def _ensure_overlay(root: Path, batch: str, name: str, state: dict) -> Path:
    out = _overlay_path(root, batch, name)
    cache = out.with_suffix(".cache.json")
    key = _render_key(_image_for(root, batch, name), state)
    try:
        valid = out.exists() and json.loads(cache.read_text())["key"] == key
    except (FileNotFoundError, ValueError, KeyError):
        valid = False
    if not valid:
        _rerender(root, batch, name, state)
    return out


def _params_from_body(body: Optional[ParamsBody]) -> SegmentParams:
    return SegmentParams(**_dump(body)) if body is not None else SegmentParams()


def _unique_target(directory: Path, filename: str) -> Path:
    name = Path(filename.replace("\\", "/")).name
    _component(name)
    target = directory / name
    index = 2
    while target.exists() or target.is_symlink():
        target = directory / f"{Path(name).stem} ({index}){Path(name).suffix}"
        index += 1
    return target


def _link_or_copy(src: Path, target: Path) -> bool:
    if target.exists() or target.is_symlink():
        return False
    try:
        target.symlink_to(src)
    except (OSError, NotImplementedError):
        shutil.copy2(src, target)
    return True


def _count_images(root: Path) -> int:
    inputs = root / "inputs"
    return sum(len(_images(root, p.name)) for p in inputs.iterdir() if p.is_dir()) if inputs.exists() else 0


def _export_name(filename: Optional[str], batch: str, extension: str) -> str:
    name = (filename or f"wecfu_{batch}").replace("\\", "/").split("/")[-1]
    name = "".join(c for c in name if ord(c) >= 32 and ord(c) != 127).strip() or "wecfu"
    return name if name.lower().endswith(extension) else name + extension


def _csv_rows(rows: list[tuple[str, Optional[dict]]]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["filename", "total_count", "machine_count", "n_removed", "n_added", "notes"])
    for name, state in rows:
        if state is None:
            writer.writerow([name, "", "", "", "", ""])
            continue
        dets = state["detections"]
        cv_remaining = sum(d.get("source") == "cv" for d in dets)
        manual = sum(d.get("source") == "manual" for d in dets)
        initial = state.get("machine_count_initial", cv_remaining)
        writer.writerow([name, len(dets), initial, initial - cv_remaining, manual, state.get("notes", "")])
    return buf.getvalue()


def build_app(get_root: Callable[[], Path], web_mode: bool = False) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            # Retire resident inference workers on a normal server shutdown,
            # including ASGI test/restart lifecycles in the same interpreter.
            import asyncio
            from .sam_warm_pool import POOL
            await asyncio.to_thread(POOL.shutdown)

    app = FastAPI(title="WeCFU", lifespan=lifespan)
    preview_manager = model_preview.ModelPreviewManager(web_mode=web_mode)
    app.state.model_preview_manager = preview_manager

    def default_params() -> SegmentParams:
        return SegmentParams() if web_mode else SegmentParams(**_INTERNAL_DEFAULT_PARAMS)

    def require_builtin_engine(engine: str) -> None:
        if web_mode and engine != "baseline":
            raise HTTPException(403, "The component counting engine is available only in the local internal app.")

    def run_params(body: Optional[ParamsBody], engine: str) -> SegmentParams:
        if engine == _COMPONENT_ENGINE:
            values = dict(_INTERNAL_DEFAULT_PARAMS)
            if body is not None:
                values.update(body.model_dump(exclude_unset=True))
            return SegmentParams(**values)
        return _params_from_body(body)

    @app.get("/api/config")
    def get_config():
        sam_capability = {**preview_manager.sam.capability(), "default_model": not web_mode}
        fusion_v2_capability = {**preview_manager.fusion_v2.capability(), "default_model": False}
        return {"web_mode": web_mode, "internal": False,
                "max_images": WEB_MAX_IMAGES if web_mode else None,
                "max_bytes": WEB_MAX_BYTES if web_mode else None,
                "builtin_algorithms": ["baseline"] if web_mode else ["baseline", _COMPONENT_ENGINE],
                "default_count_engine": "baseline" if web_mode else _COMPONENT_ENGINE,
                # Preserve the user's default intent even when its runtime is
                # unavailable. The client must report that, never silently fall
                # back to the separately selectable classical engine.
                "default_model": None if web_mode else sam_runtime.ENGINE,
                "refinement_model": sam_runtime.ENGINE,
                "recognition_policy_version": ("classical-default-explicit-sam-v1" if web_mode
                                               else "sam-default-explicit-classical-v1"),
                "recognition_policy": {
                    "default_engine": "baseline" if web_mode else sam_runtime.ENGINE,
                    "default_stages": (["classical_segmentation"] if web_mode else
                                       ["classical_seed_preparation", "sam_segmentation", "fixed_postprocessing"]),
                    "batch_scope": "unrecognized_only",
                    "refinement_engine": sam_runtime.ENGINE,
                    "refinement_scope": "current_image_explicit",
                    "automatic_refinement": False,
                    "automatic_fallback": False,
                },
                "default_model_fallback": False,
                "import_view_contract": {"default": "unknown", "values": list(source_views.VIEWS),
                                         "requires_user_declaration": False,
                                         "meaning": "Unified photo import; existing view metadata is preserved as provenance, not a separate counting recipe or human validation"},
                "default_params": _dump(ParamsBody(**asdict(default_params()))),
                "experimental_models": {"cfucounter": preview_manager.capability()},
                "models": {"sam2": sam_capability, "fusion": preview_manager.fusion.capability(), "fusion_v2": fusion_v2_capability}}

    @app.get("/api/batches")
    def list_batches():
        root = get_root()
        (root / "inputs").mkdir(parents=True, exist_ok=True)
        return {"batches": sorted(p.name for p in (root / "inputs").iterdir() if p.is_dir()), "default": _default_batch(root)}

    @app.get("/api/batch/{batch}/images")
    def list_images(batch: str):
        root = get_root()
        items = []
        for image in _images(root, batch):
            with _lock(root, batch, image.name):
                state = _maybe_state(root, batch, image.name)
                try:
                    viewed = viewed_metadata.is_viewed(root, batch, image.name, image)
                except (OSError, viewed_metadata.ViewedError):
                    # Broken/stale UI metadata must never assert browsing or
                    # alter the image's editable state or human reference.
                    viewed = False
                try:
                    view = source_views.get(root, batch, image.name, image)
                except (OSError, viewed_metadata.ViewedError):
                    view = {"view": "unknown", "declared": False}
                items.append({"name": image.name, "processed": state is not None,
                              "viewed": viewed,
                              "source_view": view["view"], "source_view_declared": view["declared"],
                              "counted": bool(state and state.get("counted", False)),
                              "count": len(state.get("detections", [])) if state else 0,
                              "reviewed": state.get("reviewed", False) if state else False,
                              "notes": state.get("notes", "") if state else "",
                              "mode": state.get("mode", "auto") if state else "auto"})
        return {"images": items}

    @app.post("/api/batch/{batch}/image/{name}/viewed")
    def mark_image_viewed(batch: str, name: str, body: ViewedBody):
        root = get_root()
        with _lock(root, batch), _lock(root, batch, name):
            image = _image_for(root, batch, name)
            try:
                return viewed_metadata.mark_viewed(root, batch, name, image, body.source_sha256)
            except (OSError, viewed_metadata.ViewedError) as exc:
                raise HTTPException(409, "Image display state could not be saved; reload the image.") from exc

    @app.post("/api/ingest")
    def ingest(body: IngestBody):
        if web_mode:
            raise HTTPException(403, "Path ingest is disabled in web mode — drag-drop files instead.")
        root = get_root()
        batch = body.batch or _default_batch(root)
        with _lock(root, batch):
            directory = _batch_dir(root, batch)
            directory.mkdir(parents=True, exist_ok=True)
            _migrate_legacy_states(root, batch)
            added = []
            for raw in body.paths:
                source = Path(raw).expanduser().resolve()
                candidates = [source] if source.is_file() else sorted(source.rglob("*")) if source.is_dir() else []
                for image in candidates:
                    if image.is_file() and image.suffix.lower() in _IMG_EXTS:
                        target = _unique_target(directory, image.name)
                        _link_or_copy(image, target)
                        try:
                            source_views.declare(root, batch, target.name, target, body.view, preserve_existing=True)
                        except (OSError, viewed_metadata.ViewedError) as exc:
                            target.unlink(missing_ok=True)
                            raise HTTPException(409, "Source view could not be bound to the imported image") from exc
                        added.append(target.name)
        return {"batch": batch, "linked": len(added), "names": added}

    @app.post("/api/upload")
    def upload(batch: str = Form(...), files: list[UploadFile] = File(...),
               view: Literal["main", "blank", "back", "unknown"] = Form("unknown")):
        root = get_root()
        with _lock(root, batch):
            if web_mode and _count_images(root) + len(files) > WEB_MAX_IMAGES:
                raise HTTPException(413, f"Per-session limit is {WEB_MAX_IMAGES} images.")
            directory = _batch_dir(root, batch)
            directory.mkdir(parents=True, exist_ok=True)
            _migrate_legacy_states(root, batch)
            added = []
            running_bytes = 0
            for uploaded in files:
                if not uploaded.filename or Path(uploaded.filename).suffix.lower() not in _IMG_EXTS:
                    continue
                out = _unique_target(directory, uploaded.filename)
                fd, temporary = tempfile.mkstemp(prefix=".upload-", dir=directory)
                try:
                    with os.fdopen(fd, "wb") as handle:
                        while chunk := uploaded.file.read(1 << 20):
                            running_bytes += len(chunk)
                            if web_mode and running_bytes > WEB_MAX_BYTES:
                                raise HTTPException(413, f"Upload exceeds {WEB_MAX_BYTES // 1024 // 1024} MB cap.")
                            handle.write(chunk)
                    os.replace(temporary, out)
                    try:
                        source_views.declare(root, batch, out.name, out, view, preserve_existing=True)
                    except (OSError, viewed_metadata.ViewedError) as exc:
                        out.unlink(missing_ok=True)
                        raise HTTPException(409, "Source view could not be bound to the uploaded image") from exc
                    added.append(out.name)
                finally:
                    Path(temporary).unlink(missing_ok=True)
        return {"batch": batch, "uploaded": len(added), "names": added}

    @app.get("/api/batch/{batch}/image/{name}/source_view")
    def get_source_view(batch: str, name: str):
        root = get_root()
        with _lock(root, batch, name):
            image = _image_for(root, batch, name)
            try:
                return source_views.get(root, batch, name, image)
            except (OSError, viewed_metadata.ViewedError) as exc:
                raise HTTPException(409, "Source view unavailable; reload the image") from exc

    @app.post("/api/batch/{batch}/image/{name}/source_view")
    def declare_source_view(batch: str, name: str, body: SourceViewBody):
        root = get_root()
        with _lock(root, batch, name):
            image = _image_for(root, batch, name)
            try:
                return source_views.declare(root, batch, name, image, body.view, expected_sha256=body.source_sha256)
            except (OSError, viewed_metadata.ViewedError) as exc:
                raise HTTPException(409, "Source changed or view could not be saved; reload the image") from exc

    @app.delete("/api/batch/{batch}/image/{name}")
    def remove_image(batch: str, name: str):
        root = get_root()
        with _lock(root, batch), _lock(root, batch, name):
            image = _image_for(root, batch, name)
            # unlink removes a symlink itself, never its original target.
            image.unlink()
            _det_path(root, batch, name).unlink(missing_ok=True)
            overlay = _overlay_path(root, batch, name)
            overlay.unlink(missing_ok=True)
            overlay.with_suffix(".cache.json").unlink(missing_ok=True)
            if not any(p.stem == Path(name).stem for p in _images(root, batch)):
                _det_path(root, batch, name).with_name(f"{Path(name).stem}.json").unlink(missing_ok=True)
                overlay.with_name(f"{Path(name).stem}.png").unlink(missing_ok=True)
        return {"ok": True}

    @app.post("/api/batch/{batch}/image/{name}/initialize")
    def initialize(batch: str, name: str, body: InitializeBody = InitializeBody()):
        root = get_root()
        with _lock(root, batch, name):
            if _assisted(root, batch):
                existing = _maybe_state(root, batch, name)
                if existing is None:
                    raise HTTPException(409, "Fixed assisted prediction is missing; initialize it offline before reviewing.")
                if body.mode != 'auto':
                    raise HTTPException(403, "Assisted review preserves its fixed machine origin.")
                return existing
            if body.mode != 'manual':
                _require_machine_assistance(root, batch)
            image = _image_for(root, batch, name)
            existing = _maybe_state(root, batch, name)
            if existing is not None:
                return existing
            pixels = _read_image(image)
            height, width = pixels.shape[:2]
            try:
                plate = detect_plate(pixels)
                diagnostics = {}
            except RuntimeError:
                # Even a plate the detector cannot locate remains manually editable.
                plate = PlateCircle(width / 2, height / 2, min(width, height) * 0.48)
                diagnostics = {"plate_fallback": True}
            state = {"plate": asdict(plate), "detections": [], "mode": body.mode,
                     "counted": False, "count_params": None,
                     "count_engine": None, "count_model": None,
                     "machine_count_initial": 0, "notes": "", "plate_manual": False,
                     "reviewed": False, "params": asdict(default_params()),
                     "diagnostics": diagnostics, "image_size": {"width": width, "height": height}}
            _save_state(root, batch, name, state)
            return state

    @app.post("/api/batch/{batch}/run")
    def run_batch(batch: str, params: Optional[ParamsBody] = None, force: bool = False,
                  engine: Literal["baseline", "component_watershed_v1"] = Query(...)):
        require_builtin_engine(engine)
        root = get_root()
        _require_machine_assistance(root, batch)
        processed, skipped, failed = 0, 0, []
        for image in _images(root, batch):
            with _lock(root, batch, image.name):
                _require_machine_assistance(root, batch)
                try:
                    _image_for(root, batch, image.name)
                    existing = _maybe_state(root, batch, image.name)
                    if existing and (existing.get("mode") == "manual" or ((existing.get("reviewed") or existing.get("counted")) and not force)):
                        skipped += 1
                        continue
                    process_image(image, _batch_dir(root, batch, "runs"), params=run_params(params, engine),
                                  force=force, write_overlay=False, engine=engine)
                    processed += 1
                except Exception as exc:
                    failed.append({"name": image.name, "error": str(exc)})
        return {"processed": processed, "skipped": skipped, "failed": failed}

    @app.post("/api/batch/{batch}/image/{name}/run")
    def run_one(batch: str, name: str, params: Optional[ParamsBody] = None,
                engine: Literal["baseline", "component_watershed_v1"] = Query(...),
                expected_revision: Optional[int] = Query(default=None, ge=0),
                protect_existing_edits: bool = False,
                only_unrecognized: bool = False,
                expected_image_sha256: Optional[str] = Query(default=None, pattern="^[0-9a-f]{64}$")):
        require_builtin_engine(engine)
        root = get_root()
        with _lock(root, batch, name):
            _require_machine_assistance(root, batch)
            image = _image_for(root, batch, name)
            if (protect_existing_edits or only_unrecognized) and expected_revision is None:
                raise HTTPException(422, "protected recount requires expected_revision")
            existing = _maybe_state(root, batch, name)

            def check_context(current):
                _require_machine_assistance(root, batch)
                if expected_revision is not None and expected_revision != int((current or {}).get("revision", 0)):
                    raise HTTPException(409, "state changed; reload before recounting")
                if only_unrecognized:
                    _require_unrecognized(root, batch, name, current or {"counted": False})
                if protect_existing_edits:
                    state = current or {}
                    reference = _reference_path(root, batch, name)
                    if (state.get("mode") == "manual" or state.get("reviewed") or state.get("plate_manual")
                            or str(state.get("notes") or "")
                            or any(mark.get("source") == "manual" for mark in state.get("detections", []))
                            or reference.exists() or reference.is_symlink()):
                        raise HTTPException(409, "existing human edits or reference are protected from bulk recount")

            check_context(existing)
            try:
                snapshot = human_reference.read_source_snapshot(image)
                if expected_image_sha256 is not None and snapshot.sha256 != expected_image_sha256:
                    raise HTTPException(409, "source differs from the displayed image; reload before recounting")
                # Keep the unchanged classical pipeline isolated until the exact
                # source, state and protection checks all pass again. This also
                # prevents external source replacement during segmentation from
                # committing detections for different bytes.
                with tempfile.TemporaryDirectory(prefix="wecfu-classical-") as temporary:
                    staging = Path(temporary)
                    frozen_image = staging / "inputs" / image.name
                    frozen_image.parent.mkdir()
                    frozen_image.write_bytes(snapshot.payload)
                    run_dir = staging / "runs"
                    output = run_dir / "detections" / (image.name + ".json")
                    if existing is not None:
                        atomic_write_json(output, existing)
                    process_image(frozen_image, run_dir, params=run_params(params, engine), force=True,
                                  write_overlay=False, overwrite_manual=True, engine=engine)
                    candidate = json.loads(output.read_bytes())
                    human_reference.assert_source_unchanged(image, snapshot)
                    current = _maybe_state(root, batch, name)
                    if current != existing:
                        raise HTTPException(409, "state changed during recounting; existing work was not replaced")
                    check_context(current)
                    candidate["revision"] = int((existing or {}).get("revision", 0))
                    _save_state(root, batch, name, candidate)
            except (OSError, human_reference.ReferenceError) as exc:
                raise HTTPException(409, "source changed or became unavailable during recounting; existing work was not replaced") from exc
            return _load_state(root, batch, name)

    def preview_call(function, *args, **kwargs):
        try:
            return function(*args, **kwargs)
        except model_preview.PreviewError as exc:
            raise HTTPException(exc.status_code, exc.detail) from exc

    def preview_source(image: Path, expected_sha256: str):
        try:
            snapshot = human_reference.read_source_snapshot(image)
            if snapshot.sha256 != expected_sha256:
                raise human_reference.ReferenceChanged("source differs from the displayed image; reload before model preview")
            return snapshot
        except human_reference.ReferenceChanged as exc:
            raise HTTPException(409, str(exc)) from exc
        except human_reference.ReferenceError as exc:
            raise HTTPException(422, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(409, "source image became unavailable; reload before model preview") from exc

    def require_preview_enabled(engine=None):
        enabled = (preview_manager.sam.enabled if engine == sam_runtime.ENGINE else
                   preview_manager.fusion.enabled if engine == fusion_runtime.ENGINE else
                   preview_manager.fusion_v2.enabled if engine == fusion_runtime_v2.ENGINE else
                   preview_manager.enabled if engine == model_preview.ENGINE else
                   (preview_manager.enabled or preview_manager.sam.enabled or preview_manager.fusion.enabled or preview_manager.fusion_v2.enabled))
        if not enabled:
            raise HTTPException(503, "The selected model is unavailable. Install/configure its runtime or explicitly choose a custom method; no fallback was run.")

    def preview_context(root: Path, batch: str, name: str, revision: int, digest: str,
                        *, only_unrecognized: bool = False):
        _require_machine_assistance(root, batch)
        image = _image_for(root, batch, name)
        state = _load_state(root, batch, name)
        if state.get("revision", 0) != revision:
            raise HTTPException(409, "state changed; reload or save edits before model preview")
        if only_unrecognized:
            _require_unrecognized(root, batch, name, state)
        if state.get("mode", "auto") != "auto":
            raise HTTPException(409, "switch to automatic assistance before model preview")
        snapshot = preview_source(image, digest)
        try:
            plate = CircleBody(**state["plate"])
            _validate_circle(plate, snapshot.width, snapshot.height)
        except (KeyError, ValueError, TypeError) as exc:
            raise HTTPException(422, "saved plate geometry is invalid") from exc
        return image, state, snapshot

    def declared_sam_view(root: Path, batch: str, name: str, image: Path, digest: str) -> str:
        """Bind the supported photo view to the exact input bytes, not its filename."""
        try:
            declaration = source_views.get(root, batch, name, image, expected_sha256=digest)
            # Unified import does not infer or rewrite a photo view. Preserve
            # any exact-byte metadata as provenance; all views use one recipe.
            return declaration["view"]
        except (OSError, RuntimeError, ValueError) as exc:
            raise HTTPException(409, str(exc)) from exc

    def recovery_folder(root, batch, name):
        return _batch_dir(root, batch, "runs") / "model_preview_recovery" / _component(name)

    def persist_recovery(root, batch, name, identifier, state, digest, candidate_id):
        folder = recovery_folder(root, batch, name)
        folder.mkdir(parents=True, exist_ok=True)
        value = {"schema_version": 1, "recovery_id": identifier,
                 "owner": [str(root.resolve()), batch, name], "source_sha256": digest,
                 "created_at_utc": datetime.now(timezone.utc).isoformat(),
                 "candidate_id": candidate_id, "state": deepcopy(state),
                 "state_sha256": model_preview.state_signature(state)}
        with (folder / (identifier + ".json")).open("x", encoding="utf8") as stream:
            json.dump(value, stream, ensure_ascii=False, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        # The directory entry must also survive an app crash before adoption.
        descriptor = os.open(folder, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @app.get("/api/batch/{batch}/image/{name}/model-preview/recovery")
    def list_model_recovery(batch: str, name: str):
        if web_mode:
            raise HTTPException(403, "Recovery is available only in the local internal app")
        root = get_root()
        with _lock(root, batch, name):
            _require_machine_assistance(root, batch)
            _load_state(root, batch, name)
            items = []
            for path in sorted(recovery_folder(root, batch, name).glob("*.json")):
                value = json.loads(path.read_bytes())
                if value.get("owner") != [str(root.resolve()), batch, name]:
                    continue
                items.append({key: value[key] for key in ("recovery_id", "source_sha256", "created_at_utc")})
            return {"snapshots": items}

    @app.post("/api/batch/{batch}/image/{name}/model-preview/restore")
    def restore_model_recovery(batch: str, name: str, body: RestoreModelPreviewBody):
        if web_mode:
            raise HTTPException(403, "Recovery is available only in the local internal app")
        root = get_root()
        with _lock(root, batch, name):
            _require_machine_assistance(root, batch)
            image = _image_for(root, batch, name)
            state = _load_state(root, batch, name)
            if state.get("revision", 0) != body.expected_revision:
                raise HTTPException(409, "state changed; reload before recovery")
            snapshot = preview_source(image, body.expected_image_sha256)
            path = recovery_folder(root, batch, name) / (body.recovery_id + ".json")
            if not path.is_file():
                raise HTTPException(404, "recovery snapshot not found")
            value = json.loads(path.read_bytes())
            if (value.get("owner") != [str(root.resolve()), batch, name]
                    or value.get("source_sha256") != snapshot.sha256
                    or value.get("state_sha256") != model_preview.state_signature(value.get("state"))):
                raise HTTPException(409, "recovery source or state integrity differs")
            restored = deepcopy(value["state"])
            # Keep the pre-recovery current state too; recovery never erases a
            # newer edit without a durable path back. No reference is modified.
            persist_recovery(root, batch, name, uuid4().hex, state, snapshot.sha256, "restore:" + body.recovery_id)
            restored["revision"] = state.get("revision", 0)
            restored.pop("_model_preview_apply", None)
            human_reference.assert_source_unchanged(image, snapshot)
            _save_state(root, batch, name, restored)
            return restored

    @app.post("/api/batch/{batch}/image/{name}/model-preview")
    def create_model_preview(batch: str, name: str, body: ModelPreviewBody):
        if body.only_unrecognized and (web_mode or body.engine != sam_runtime.ENGINE):
            raise HTTPException(409, "Model batch recognition supports only local SAM. Reload the page before continuing; no fallback was run.")
        if body.engine in _FUSION_ENGINES:
            raise HTTPException(409, "Fine refinement now uses SAM without DINO. Reload the page before continuing; saved Fusion results are preserved.")
        require_preview_enabled(body.engine)
        root = get_root()
        started = time.perf_counter()
        timeout_seconds = (preview_manager.fusion_v2.timeout_seconds
                           if body.engine == fusion_runtime_v2.ENGINE else fusion_runtime.TIMEOUT_SECONDS)
        deadline = time.monotonic() + timeout_seconds
        fusion_provenance = None
        sam_view = None
        with _lock(root, batch, name):
            image, state, snapshot = preview_context(root, batch, name, body.expected_revision,
                                                     body.expected_image_sha256,
                                                     only_unrecognized=body.only_unrecognized)
            saved_inset = state.get("params", {}).get("plate_inset", SegmentParams.plate_inset)
            if body.engine == model_preview.ENGINE and body.model_params.plate_inset != saved_inset:
                raise HTTPException(409, "model ROI differs from saved parameters; save the current parameters first")
            if body.engine == sam_runtime.ENGINE:
                sam_view = declared_sam_view(root, batch, name, image, snapshot.sha256)
            if body.engine in _FUSION_ENGINES:
                if state.get("plate_manual"):
                    raise HTTPException(409, "Fusion requires an automatic medium boundary; the current manual boundary will not be replaced")
                try:
                    version = fusion_runtime_v2 if body.engine == fusion_runtime_v2.ENGINE else fusion_runtime
                    declaration = source_views.get(root, batch, name, image, expected_sha256=snapshot.sha256)
                    fusion_view = version.view_for_source(snapshot.sha256, declaration)
                    automatic = asdict(detect_plate(snapshot.pixels))
                except (RuntimeError, ValueError) as exc:
                    raise HTTPException(409, str(exc)) from exc
                if any(abs(automatic[k] - state["plate"][k]) > 1e-6 for k in ("cx", "cy", "r")):
                    raise HTTPException(409, "Saved boundary differs from the automatic boundary required by fusion; no circle was changed")
            signature = model_preview.state_signature(state)
        # Intentionally outside the image lock: edits can proceed while inference
        # runs. Neither a canceled browser request nor an old response can adopt.
        if body.engine in _FUSION_ENGINES:
            detections, raw_count, fusion_provenance = preview_call(preview_manager.predict_fusion, snapshot.payload,
                PlateCircle(**state["plate"]), snapshot.sha256, snapshot.width, snapshot.height, fusion_view, deadline=deadline, engine=body.engine)
            model_params = {"plate_inset": .95}
        elif body.engine == sam_runtime.ENGINE:
            detections, raw_count = preview_call(preview_manager.predict_sam, snapshot.payload,
                                                 PlateCircle(**state["plate"]), snapshot.sha256)
            model_params = {"plate_inset": sam_runtime.PLATE_INSET}
        else:
            detections, raw_count = preview_call(preview_manager.predict, snapshot.pixels,
                                                  PlateCircle(**state["plate"]), body.model_params.plate_inset)
            model_params = {"plate_inset": body.model_params.plate_inset,
                            "score_threshold": model_preview.SCORE_THRESHOLD,
                            "nms_threshold": model_preview.NMS_THRESHOLD}
        try:
            if type(raw_count) is not int or raw_count < len(detections) or len(detections) > 20000:
                raise ValueError("invalid model output count")
            validated = [DetectionBody(**item) for item in detections]
            for detection in validated:
                _validate_circle(detection, snapshot.width, snapshot.height)
            if len({d.id for d in validated}) != len(validated) or any(d.source != "cv" for d in validated):
                raise ValueError("invalid detection identity")
            if body.engine in _FUSION_ENGINES:
                _fusion_model_body(body.engine).model_validate(fusion_provenance)
                if (fusion_provenance["image_sha256"] != snapshot.sha256 or fusion_provenance["automatic_plate"] != state["plate"]
                        or fusion_provenance["candidate_count"] != len(validated) or fusion_provenance["raw_count"] != raw_count):
                    raise ValueError("fusion provenance differs from actual candidate")
        except (ValueError, TypeError, HTTPException) as exc:
            raise HTTPException(503, "model produced invalid candidate geometry; no candidate was created") from exc
        with _lock(root, batch, name):
            try:
                _, current, final_snapshot = preview_context(root, batch, name, body.expected_revision,
                                                            snapshot.sha256,
                                                            only_unrecognized=body.only_unrecognized)
            except HTTPException as exc:
                if exc.status_code == 404:
                    raise HTTPException(409, "image or state changed during model preview") from exc
                raise
            if model_preview.state_signature(current) != signature:
                raise HTTPException(409, "state changed during model preview; run a new preview")
            if body.engine == sam_runtime.ENGINE:
                if declared_sam_view(root, batch, name, image, snapshot.sha256) != sam_view:
                    raise HTTPException(409, "Source view changed during preview; request a new SAM preview")
            if body.engine == fusion_runtime_v2.ENGINE:
                try:
                    declared = source_views.get(root, batch, name, image, expected_sha256=snapshot.sha256)
                    if fusion_runtime_v2.view_for_source(snapshot.sha256, declared) != fusion_view:
                        raise ValueError("Source view changed during preview")
                except (OSError, RuntimeError, ValueError) as exc:
                    raise HTTPException(409, "Source view changed during model preview; request a new preview") from exc
            try:
                human_reference.assert_source_unchanged(image, final_snapshot)
            except (OSError, human_reference.ReferenceChanged) as exc:
                raise HTTPException(409, "source changed during model preview; reload the image") from exc
            if body.engine in _FUSION_ENGINES and time.monotonic() >= deadline:
                raise HTTPException(503, "Fusion exceeded the shared deadline; no candidate was created")
            return preview_manager.create_candidate(
                (str(root.resolve()), batch, name), current, snapshot.sha256,
                model_params, [_dump(d) for d in validated], raw_count,
                (time.perf_counter() - started) * 1000, engine=body.engine, fusion_provenance=fusion_provenance,
                source_view=sam_view,
                only_unrecognized=body.only_unrecognized,
            )

    @app.post("/api/batch/{batch}/image/{name}/model-preview/apply")
    def apply_model_preview(batch: str, name: str, body: ApplyModelPreviewBody):
        root = get_root()
        with _lock(root, batch, name):
            _require_machine_assistance(root, batch)
            image = _image_for(root, batch, name)
            state = _load_state(root, batch, name)
            snapshot = preview_source(image, body.expected_image_sha256)
            request = _dump(body)
            if not body.only_unrecognized:
                # Keep previously persisted explicit single-image retry receipts valid.
                request.pop("only_unrecognized")
            receipt = state.get("_model_preview_apply")
            if receipt and receipt.get("request_id") == body.request_id:
                if receipt.get("request") != request:
                    raise HTTPException(409, "request_id was already used with a different model adoption request")
                if receipt.get("applied_revision") != state.get("revision", 0):
                    raise HTTPException(409, "adoption succeeded earlier, but the state has since changed; reload the current state")
                # Return the current persisted document only; never replay an old
                # cached document over edits made after the successful adoption.
                return state
            if state.get("revision", 0) != body.expected_revision:
                raise HTTPException(409, "state changed; run a new model preview before replacing marks")
            record = preview_call(preview_manager.candidate, body.candidate_id, (str(root.resolve()), batch, name))
            candidate = record["result"]
            if candidate["engine"] in _FUSION_ENGINES:
                raise HTTPException(409, "Fine refinement now uses SAM without DINO. Reload the page before continuing; saved Fusion results are preserved.")
            if body.only_unrecognized and (web_mode or candidate["engine"] != sam_runtime.ENGINE):
                raise HTTPException(409, "Model batch recognition supports only local SAM. Reload the page before continuing; no fallback was run.")
            if bool(record.get("only_unrecognized", False)) != body.only_unrecognized:
                raise HTTPException(409, "Model preview batch intent changed. Reload the page and request a matching preview before adoption.")
            if body.only_unrecognized:
                _require_unrecognized(root, batch, name, state)
            require_preview_enabled(candidate["engine"])
            is_sam = candidate["engine"] == sam_runtime.ENGINE
            is_fusion = candidate["engine"] in _FUSION_ENGINES
            if is_sam:
                current_view = declared_sam_view(root, batch, name, image, snapshot.sha256)
                if current_view != candidate.get("source_view"):
                    raise HTTPException(409, "Source view changed since model preview; request a new SAM preview")
            if candidate["engine"] == fusion_runtime_v2.ENGINE:
                try:
                    declaration = source_views.get(root, batch, name, image, expected_sha256=snapshot.sha256)
                    current_view = fusion_runtime_v2.view_for_source(snapshot.sha256, declaration)
                    if current_view != candidate.get("fusion_provenance", {}).get("source_view"):
                        raise ValueError("Source view changed since model preview")
                except (OSError, RuntimeError, ValueError) as exc:
                    raise HTTPException(409, "Source view changed; request a new model preview") from exc
            candidate_model = {"model_sha256": candidate["model_sha256"], "image_sha256": candidate["image_sha256"],
                               **candidate["model_params"], "raw_count": candidate["raw_count"],
                               "candidate_count": candidate["candidate_count"]}
            if is_sam:
                candidate_model["recipe_id"] = candidate.get("recipe_id")
            if is_fusion:
                candidate_model = deepcopy(candidate.get("fusion_provenance"))
            try:
                (_fusion_model_body(candidate["engine"]) if is_fusion else LocalSamModelBody if is_sam else CountModelBody).model_validate(candidate_model)
                if is_fusion and (candidate_model["model_sha256"] != candidate["model_sha256"] or candidate_model["recipe_id"] != candidate["recipe_id"]
                        or candidate_model["image_sha256"] != snapshot.sha256 or candidate_model["automatic_plate"] != state["plate"]
                        or candidate_model["candidate_count"] != candidate["candidate_count"] or candidate_model["raw_count"] != candidate["raw_count"]):
                    raise ValueError("fusion candidate binding differs")
            except ValueError as exc:
                raise HTTPException(409, "candidate model provenance changed") from exc
            if (candidate["base_revision"] != body.expected_revision or candidate["image_sha256"] != snapshot.sha256
                    or record["state_signature"] != model_preview.state_signature(state)
                    or state.get("mode", "auto") != "auto"
                    or candidate["plate"] != state.get("plate")
                    or (is_fusion and state.get("plate_manual"))
                    or (not is_sam and not is_fusion and candidate["model_params"]["plate_inset"] != state.get("params", {}).get("plate_inset", SegmentParams.plate_inset))):
                raise HTTPException(409, "candidate context changed; run a new model preview")
            before_state = deepcopy(state)
            recovery_id = uuid4().hex
            state.update(detections=candidate["detections"], mode="auto", counted=True, reviewed=False,
                         machine_count_initial=candidate["candidate_count"], count_params=None,
                         count_engine=candidate["engine"], count_model=candidate_model,
                         image_size={"width": snapshot.width, "height": snapshot.height},
                         diagnostics={"algorithm": candidate["engine"], "raw_count": candidate["raw_count"],
                                      "candidate_count": candidate["candidate_count"],
                                      "display_radius_note": ("SAM D0 circles retained; supplementary box-derived rings only locate centers, not colony outlines" if is_fusion else "circles enclose the largest mask contour; mask quality is not colony probability" if is_sam
                                                              else "circles approximate model boxes, not colony contours")})
            state["_model_preview_apply"] = {"request_id": body.request_id, "request": request,
                                              "applied_revision": body.expected_revision + 1, "recovery_id": recovery_id}
            try:
                human_reference.assert_source_unchanged(image, snapshot)
            except (OSError, human_reference.ReferenceChanged) as exc:
                raise HTTPException(409, "source changed before adoption; reload the image") from exc
            if body.only_unrecognized:
                _require_unrecognized(root, batch, name, before_state)
            persist_recovery(root, batch, name, recovery_id, before_state, snapshot.sha256, body.candidate_id)
            try:
                human_reference.assert_source_unchanged(image, snapshot)
            except (OSError, human_reference.ReferenceChanged) as exc:
                raise HTTPException(409, "source changed before adoption; reload the image") from exc
            if body.only_unrecognized:
                _require_unrecognized(root, batch, name, before_state)
            _save_state(root, batch, name, state)
            return state

    @app.post("/api/batch/{batch}/image/{name}/mask_preview.png")
    def mask_preview(batch: str, name: str, params: ParamsBody):
        root = get_root()
        _require_machine_assistance(root, batch)
        pixels = _read_image(_image_for(root, batch, name))
        state = _maybe_state(root, batch, name)
        plate = PlateCircle(**state["plate"]) if state else detect_plate(pixels)
        settings = _params_from_body(params)
        height, width = pixels.shape[:2]
        bw = _white_colony_mask(pixels, plate.mask((height, width), shrink=settings.plate_inset), settings.min_value, settings.max_saturation)
        out = pixels.copy()
        selected = bw > 0
        # OpenCV BGR for RGB (50, 235, 165); the UI applies its existing alpha.
        out[selected] = (165, 235, 50)
        from ..overlay import _crop_to_plate
        out, _, _ = _crop_to_plate(out, plate)
        ok, buffer = cv2.imencode(".png", out, [cv2.IMWRITE_PNG_COMPRESSION, 1])
        if not ok:
            raise HTTPException(500, "encode failed")
        return Response(content=buffer.tobytes(), media_type="image/png",
                        headers={"Cache-Control": "no-store"})

    @app.get("/api/batch/{batch}/image/{name}/detections")
    def get_state(batch: str, name: str):
        return _load_state(get_root(), batch, name)

    def require_local_references():
        if web_mode:
            raise HTTPException(403, "Human reference annotation is available only in the local internal app.")

    @app.get("/api/review-queues/{queue_id}")
    def get_review_queue(queue_id: str, response: Response):
        require_local_references()
        root = get_root()
        queue = review_queues.load_queue(root, queue_id)
        batch = queue['batch']
        queue['annotation_mode'] = review_queues.annotation_mode_for_batch(root, batch)
        if (root / 'inputs').is_symlink() or not _batch_dir(root, batch).resolve().is_relative_to(root.resolve()):
            raise HTTPException(400, "review queue batch must belong to this workspace")
        # Hold the batch lock against removal/import while resolving all queue
        # members. Per-image locks protect each current reference inspection.
        with _lock(root, batch):
            _images(root, batch)
            for item in queue['items']:
                _image_for(root, batch, item['name'])
            for item in queue['items']:
                with _lock(root, batch, item['name']):
                    try:
                        item['reference_status'] = _reference_status(root, batch, item['name'], strict_audit=True)['status']
                    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
                        raise HTTPException(409, "review queue reference state cannot be read; repair it before continuing") from exc
        response.headers['Cache-Control'] = 'no-store'
        return queue

    @app.get("/api/batch/{batch}/image/{name}/reference")
    def get_reference(batch: str, name: str):
        require_local_references()
        root = get_root()
        with _lock(root, batch, name):
            return _reference_status(root, batch, name)

    @app.post("/api/batch/{batch}/image/{name}/reference")
    def confirm_reference(batch: str, name: str, body: ConfirmReferenceBody):
        require_local_references()
        if body.human_confirmed is not True:
            raise HTTPException(422, "human_confirmed must be literal true after reviewing the displayed image")
        annotator = body.annotator.strip()
        group_id = body.group_id.strip() if body.group_id else None
        if not annotator or any(ord(char) < 32 for char in annotator):
            raise HTTPException(422, "annotator must be a nonempty code without control characters")
        if group_id and any(ord(char) < 32 for char in group_id):
            raise HTTPException(422, "group_id must not contain control characters")
        root = get_root()
        with _lock(root, batch, name):
            image = _image_for(root, batch, name)
            state = _load_state(root, batch, name)
            if body.expected_revision != state.get("revision", 0):
                raise HTTPException(409, "state changed; reload and review before confirming a reference")
            try:
                snapshot = human_reference.read_source_snapshot(image)
                if snapshot.sha256 != body.expected_image_sha256:
                    raise human_reference.ReferenceChanged("source differs from the displayed reference view; reload and review it")
                annotation_context = None
                if _assisted(root, batch):
                    if state['count_model']['image_sha256'] != snapshot.sha256:
                        raise human_reference.ReferenceChanged("source differs from the frozen prediction image")
                    annotation_context = {'mode': 'assisted_frozen', 'assisted': True, 'blinded': False,
                                          'count_engine': state['count_engine'], 'count_model': state['count_model'],
                                          'machine_count_initial': state['machine_count_initial']}
                document = human_reference.create_reference(
                    _reference_path(root, batch, name), image, name, state, snapshot,
                    annotator=annotator, group_id=group_id or None, annotation_context=annotation_context,
                    review_scope=_dump(body.review_scope) if body.review_scope is not None else None,
                )
            except human_reference.ReferenceChanged as exc:
                raise HTTPException(409, str(exc)) from exc
            except human_reference.ReferenceError as exc:
                raise HTTPException(422, str(exc)) from exc
            return human_reference.inspect_reference(document, state, snapshot)

    @app.delete("/api/batch/{batch}/image/{name}/reference")
    def withdraw_reference(batch: str, name: str, body: WithdrawReferenceBody):
        require_local_references()
        root = get_root()
        with _lock(root, batch, name):
            _image_for(root, batch, name)
            state = _maybe_state(root, batch, name)
            path = _reference_path(root, batch, name)
            document = human_reference.load_document(path)
            record = human_reference.current_record(document)
            if record is None or record["reference_id"] != body.expected_reference_id:
                raise HTTPException(409, "reference changed; reload before withdrawing")
            document = human_reference.withdraw_reference(path)
            return human_reference.inspect_reference(document, state)

    @app.get("/api/batch/{batch}/references.json")
    def export_references(batch: str):
        require_local_references()
        root = get_root()
        annotations, excluded = [], []
        counts = {status: 0 for status in ("verified", "missing", "stale", "withdrawn")}
        for image in _images(root, batch):
            with _lock(root, batch, image.name):
                result = _reference_status(root, batch, image.name)
                counts[result["status"]] += 1
                if result["status"] == "verified":
                    annotations.append(result["reference"])
                else:
                    excluded.append({"path": image.name, "status": result["status"], "reasons": result["reasons"]})
        return {"schema_version": 1, "annotations": annotations, "excluded": excluded,
                "status_counts": counts, "batch": batch,
                "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "grouping_confirmed": False,
                "grouping_note": "Human reference confirmation does not establish independent train/dev/test grouping."}

    @app.put("/api/batch/{batch}/image/{name}/state")
    def replace_state(batch: str, name: str, body: StateBody):
        if web_mode and body.count_engine == _COMPONENT_ENGINE:
            require_builtin_engine(body.count_engine)
        root = get_root()
        with _lock(root, batch, name):
            if _manual_only(root, batch) and (
                    body.mode != 'manual' or body.machine_count_initial != 0 or body.counted is True
                    or body.count_engine is not None or body.count_model is not None or body.count_params is not None
                    or any(d.source != 'manual' for d in body.detections)):
                raise HTTPException(403, "Manual-only annotation accepts only manual marks and null machine provenance.")
            pixels = _read_image(_image_for(root, batch, name))
            height, width = pixels.shape[:2]
            _validate_circle(body.plate, width, height)
            ids = [d.id for d in body.detections]
            if len(ids) != len(set(ids)):
                raise HTTPException(422, "detection IDs must be unique")
            if sum(d.source == "cv" for d in body.detections) > body.machine_count_initial:
                raise HTTPException(422, "machine_count_initial cannot be lower than remaining machine detections")
            for detection in body.detections:
                _validate_circle(detection, width, height)
            state = _maybe_state(root, batch, name) or {}
            if _assisted(root, batch):
                supplied = body.model_fields_set
                saved_model = (_dump(body.count_model) if body.count_model is not None else None) if 'count_model' in supplied else state.get('count_model')
                saved_engine = body.count_engine if 'count_engine' in supplied else state.get('count_engine')
                saved_counted = body.counted if 'counted' in supplied else state.get('counted')
                if (body.mode != 'auto' or saved_counted is not True or saved_engine != _SAM_FROZEN_ENGINE
                        or body.count_params is not None
                        or body.machine_count_initial != state.get('machine_count_initial')
                        or saved_model != state.get('count_model')
                        or (body.params is not None and asdict(_params_from_body(body.params)) != state.get('params'))):
                    raise HTTPException(403, "Assisted edits must preserve the initial machine count and frozen model provenance.")
            if body.expected_revision is not None and body.expected_revision != state.get("revision", 0):
                raise HTTPException(409, "state changed; reload before saving")
            fields = _dump(body)
            fields.pop("expected_revision", None)
            fields.pop("params", None)
            fields.pop("counted", None)
            fields.pop("count_params", None)
            fields.pop("count_engine", None)
            fields.pop("count_model", None)
            old_provenance = (state.get("count_engine"), state.get("count_model"))
            state.update(fields)
            if body.params is not None:
                state["params"] = asdict(_params_from_body(body.params))
            if body.counted is not None:
                state["counted"] = body.counted
            provided = body.model_fields_set if hasattr(body, "model_fields_set") else body.__fields_set__
            if "count_params" in provided:
                state["count_params"] = asdict(_params_from_body(body.count_params)) if body.count_params is not None else None
            if "count_engine" in provided:
                state["count_engine"] = body.count_engine
            if "count_model" in provided:
                state["count_model"] = _dump(body.count_model) if body.count_model is not None else None
            _state_provenance_defaults(state)
            if body.mode == "manual" or state.get("counted") is False:
                state.update(count_engine=None, count_model=None, count_params=None)
            elif state.get("count_engine") == model_preview.ENGINE:
                provenance = state.get("count_model")
                try:
                    CountModelBody.model_validate(provenance)
                except ValueError as exc:
                    raise HTTPException(422, "invalid saved CFUCounter model provenance") from exc
                if (provenance["candidate_count"] != body.machine_count_initial
                        or state.get("count_params") is not None):
                    raise HTTPException(422, "model count provenance must match its machine baseline and use null count_params")
            elif state.get("count_engine") in (sam_runtime.ENGINE, *_FUSION_ENGINES):
                provenance = state.get("count_model")
                try:
                    (_fusion_model_body(state.get("count_engine")) if state.get("count_engine") in _FUSION_ENGINES else LocalSamModelBody).model_validate(provenance)
                except ValueError as exc:
                    raise HTTPException(422, "invalid saved local SAM2 provenance") from exc
                if provenance["candidate_count"] != body.machine_count_initial or state.get("count_params") is not None:
                    raise HTTPException(422, "SAM2 provenance must preserve its machine baseline and null count_params")
            elif state.get('count_engine') == _SAM_FROZEN_ENGINE:
                if not _assisted(root, batch):
                    raise HTTPException(403, "Frozen SAM results are editable only in an assisted review batch.")
                _check_assisted_state(root, batch, state)
            else:
                if body.count_model is not None:
                    raise HTTPException(422, "model provenance requires the model count_engine")
                state["count_model"] = None
            if old_provenance != (state.get("count_engine"), state.get("count_model")):
                engine = state.get("count_engine")
                state["diagnostics"] = {"algorithm": engine, "restored_from_snapshot": True} if engine else {}
                if engine in (model_preview.ENGINE, sam_runtime.ENGINE, *_FUSION_ENGINES):
                    state["diagnostics"].update(raw_count=state["count_model"]["raw_count"],
                                                candidate_count=state["count_model"]["candidate_count"],
                                                display_radius_note=("SAM D0 circles retained; supplementary rings locate centers and are not segmentation masks"
                                                                     if engine in _FUSION_ENGINES else "circles enclose the largest mask contour; mask quality is not colony probability"
                                                                     if engine == sam_runtime.ENGINE else
                                                                     "circles approximate model boxes, not colony contours"))
            state.setdefault("params", asdict(SegmentParams()))
            state["image_size"] = {"width": width, "height": height}
            _save_state(root, batch, name, state)
            return state

    @app.post("/api/batch/{batch}/image/{name}/detections")
    def add_det(batch: str, name: str, body: AddDetectionBody):
        root = get_root()
        with _lock(root, batch, name):
            height, width = _read_image(_image_for(root, batch, name)).shape[:2]
            _validate_circle(body, width, height)
            state = _load_state(root, batch, name)
            next_id = max((d["id"] for d in state["detections"]), default=0) + 1
            state["detections"].append(Detection(id=next_id, cx=body.cx, cy=body.cy, r=body.r, source="manual").asdict())
            state["reviewed"] = True
            _save_state(root, batch, name, state)
            return {"id": next_id}

    @app.delete("/api/batch/{batch}/image/{name}/detections/{det_id}")
    def delete_det(batch: str, name: str, det_id: int):
        root = get_root()
        with _lock(root, batch, name):
            state = _load_state(root, batch, name)
            detections = [d for d in state["detections"] if d["id"] != det_id]
            if len(detections) == len(state["detections"]):
                raise HTTPException(404, f"detection {det_id} not found")
            state.update(detections=detections, reviewed=True)
            _save_state(root, batch, name, state)
            return {"ok": True}

    @app.post("/api/batch/{batch}/image/{name}/reviewed")
    def mark_reviewed(batch: str, name: str, reviewed: bool = True):
        root = get_root()
        with _lock(root, batch, name):
            state = _load_state(root, batch, name)
            state["reviewed"] = reviewed
            _save_state(root, batch, name, state)
        return {"ok": True}

    @app.put("/api/batch/{batch}/image/{name}/notes")
    def set_notes(batch: str, name: str, body: NotesBody):
        root = get_root()
        with _lock(root, batch, name):
            state = _load_state(root, batch, name)
            state["notes"] = body.notes
            _save_state(root, batch, name, state)
        return {"ok": True}

    @app.get("/api/batch/{batch}/image/{name}/raw")
    def serve_raw(batch: str, name: str, reference_context: bool = False,
                  display_context: bool = False):
        root = get_root()
        if reference_context:
            require_local_references()
        if reference_context or display_context:
            with _lock(root, batch, name):
                path = _image_for(root, batch, name)
                try:
                    snapshot = human_reference.read_source_snapshot(path)
                except human_reference.ReferenceChanged as exc:
                    raise HTTPException(409, str(exc)) from exc
                except human_reference.ReferenceError as exc:
                    raise HTTPException(422, str(exc)) from exc
                content = snapshot.payload
                if path.suffix.lower() in {".tif", ".tiff"}:
                    ok, encoded = cv2.imencode(".jpg", snapshot.pixels, [cv2.IMWRITE_JPEG_QUALITY, 95])
                    if not ok:
                        raise HTTPException(500, "reference preview encoding failed")
                    content = encoded.tobytes()
                media_type = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
                return Response(content=content, media_type=media_type, headers={
                    "X-WeCFU-Source-SHA256": snapshot.sha256, "Cache-Control": "no-store",
                })
        path = _image_for(root, batch, name)
        if path.suffix.lower() in {".tif", ".tiff"}:
            stat = path.stat()
            return Response(
                content=_tiff_browser_preview(str(path), stat.st_mtime_ns, stat.st_size),
                media_type="image/jpeg",
                headers={"Cache-Control": "private, max-age=0, must-revalidate"},
            )
        return FileResponse(path)

    @app.get("/api/batch/{batch}/image/{name}/overlay")
    def serve_overlay(batch: str, name: str):
        root = get_root()
        with _lock(root, batch, name):
            return FileResponse(_ensure_overlay(root, batch, name, _load_state(root, batch, name)))

    @app.get("/api/batch/{batch}/export.csv")
    def export_csv(batch: str, filename: Optional[str] = None):
        root = get_root()
        rows = []
        for image in _images(root, batch):
            with _lock(root, batch, image.name):
                rows.append((image.name, _maybe_state(root, batch, image.name)))
        name = _export_name(filename, batch, ".csv")
        return Response(content=_csv_rows(rows), media_type="text/csv",
                        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})

    @app.get("/api/batch/{batch}/export.zip")
    def export_bundle(batch: str, filename: Optional[str] = None):
        root = get_root()
        images = _images(root, batch)
        name = _export_name(filename, batch, ".zip")
        temporary_dir = root / "exports"
        temporary_dir.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix="wecfu-", suffix=".zip", dir=temporary_dir)
        os.close(fd)
        rows = []
        try:
            with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
                for image in images:
                    with _lock(root, batch, image.name):
                        state = _maybe_state(root, batch, image.name)
                        rows.append((image.name, state))
                        if state is None:
                            continue
                        overlay = _ensure_overlay(root, batch, image.name, state)
                        archive.write(overlay, arcname=f"overlays/{overlay.name}", compress_type=zipfile.ZIP_STORED)
                        archive.writestr(f"detections/{image.name}.json", json.dumps(state, ensure_ascii=False, separators=(",", ":")))
                archive.writestr(f"{name[:-4]}.csv", _csv_rows(rows))
            return FileResponse(temporary, filename=name, media_type="application/zip",
                                background=BackgroundTask(Path(temporary).unlink, missing_ok=True))
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise

    app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")

    @app.get("/")
    def index():
        return FileResponse(_STATIC / "index.html")

    return app
