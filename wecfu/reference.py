"""Explicit human reference attestations, separate from editable counter state.

This module never infers truth from reviewed/mode/source fields. Sidecars retain
all attested records and withdrawal events. A currently usable reference must
match exact source bytes and the explicitly reviewed geometry. Legacy records
retain their original full-geometry binding. Source and
state locks belong to the API caller; external source edits are guarded by a
stable byte snapshot and a final file fingerprint check.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
from uuid import uuid4

import cv2
import numpy as np

from .pipeline import atomic_write_json


class ReferenceError(ValueError):
    """Invalid reference input; never silently treated as verified."""


class ReferenceChanged(ReferenceError):
    """The reviewed source changed while preparing an attestation."""


@dataclass
class SourceSnapshot:
    payload: bytes
    pixels: np.ndarray
    sha256: str
    width: int
    height: int
    fingerprint: tuple


def _fingerprint(stat) -> tuple:
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


def _path_fingerprint(path: Path) -> tuple:
    # Keep comparisons in the same API domain: Windows path stat and fstat
    # can give different ctime values (creation time versus change time).
    # Reopen the path so a replaced file cannot inherit an earlier snapshot.
    with path.open("rb") as source:
        return _fingerprint(os.fstat(source.fileno()))


def read_source_snapshot(path: Path) -> SourceSnapshot:
    """Hash and decode the same bytes, rejecting concurrent file replacement."""
    with path.open("rb") as source:
        before = _fingerprint(os.fstat(source.fileno()))
        payload = source.read()
        after = _fingerprint(os.fstat(source.fileno()))
    if before != after or _path_fingerprint(path) != after or len(payload) != after[2]:
        raise ReferenceChanged("source image changed while reading; reload the reference view")
    pixels = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
    if pixels is None:
        raise ReferenceError("source image cannot be decoded")
    height, width = pixels.shape[:2]
    return SourceSnapshot(payload, pixels, hashlib.sha256(payload).hexdigest(), width, height, after)


def assert_source_unchanged(path: Path, snapshot: SourceSnapshot) -> None:
    if _path_fingerprint(path) != snapshot.fingerprint:
        raise ReferenceChanged("source image changed; reload the reference view before confirming")


def _number(value, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ReferenceError(f"{label} must be finite numeric")
    value = float(value)
    return 0.0 if value == 0 else value


def canonical_geometry(state: dict, width: int, height: int) -> dict:
    """Ignore ID/order/provenance; preserve every visible mark and exact geometry."""
    try:
        plate = {key: _number(state["plate"][key], f"plate {key}") for key in ("cx", "cy", "r")}
        if not (0 <= plate["cx"] <= width and 0 <= plate["cy"] <= height
                and 0 < plate["r"] <= math.hypot(width, height)):
            raise ReferenceError("plate geometry is outside image bounds")
        marks = []
        for detection in state["detections"]:
            x, y, radius = (_number(detection[key], f"detection {key}") for key in ("cx", "cy", "r"))
            if not (0 <= x < width and 0 <= y < height and 0 < radius <= math.hypot(width, height)):
                raise ReferenceError("reference points must satisfy 0 <= x < width and 0 <= y < height, with positive finite radii")
            marks.append([x, y, radius])
    except (KeyError, TypeError) as exc:
        raise ReferenceError("editable state has incomplete plate/mark geometry") from exc
    return {"plate": plate, "detections_geometry": sorted(marks)}


def geometry_sha256(geometry: dict) -> str:
    return hashlib.sha256(json.dumps(geometry, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def canonical_review_scope(value: dict) -> dict:
    """Validate an explicit count/center attestation; never infer crop review."""
    fields = {"colony_count_reviewed", "colony_center_points_reviewed", "plate_crop_reviewed",
              "plate_circle_reviewed", "colony_outline_or_mark_radius_ground_truth"}
    if not isinstance(value, dict) or set(value) - fields:
        raise ReferenceError("review_scope must contain only supported review fields")
    if (value.get("colony_count_reviewed") is not True
            or value.get("colony_center_points_reviewed") is not True
            or type(value.get("plate_crop_reviewed")) is not bool):
        raise ReferenceError("count and center review must be literal true; crop review must be an explicit boolean")
    crop = value["plate_crop_reviewed"]
    if "plate_circle_reviewed" in value and (type(value["plate_circle_reviewed"]) is not bool
                                            or value["plate_circle_reviewed"] != crop):
        raise ReferenceError("plate circle and crop review must agree")
    if "colony_outline_or_mark_radius_ground_truth" in value and value["colony_outline_or_mark_radius_ground_truth"] is not False:
        raise ReferenceError("mark radii and colony outlines are not confirmed by this workflow")
    return {"colony_count_reviewed": True, "colony_center_points_reviewed": True,
            "plate_crop_reviewed": crop, "plate_circle_reviewed": crop,
            "colony_outline_or_mark_radius_ground_truth": False}


def reviewed_geometry(geometry: dict, scope: dict) -> dict:
    """Centers/count are always reviewed; crop is opt-in; radii are never truth."""
    scope = canonical_review_scope(scope)
    result = {"points": sorted(mark[:2] for mark in geometry["detections_geometry"])}
    if scope["plate_crop_reviewed"]:
        result["plate"] = geometry["plate"]
    return result


def load_document(path: Path) -> dict | None:
    if not path.exists():
        return None
    document = json.loads(path.read_text(encoding="utf-8"))
    if (document.get("schema_version") != 1 or not isinstance(document.get("records"), list)
            or not isinstance(document.get("events"), list)):
        raise ReferenceError("reference audit has an unsupported or damaged schema")
    return document


def current_record(document: dict | None) -> dict | None:
    if document is None:
        return None
    identifier = document.get("current_reference_id")
    return next((record for record in reversed(document["records"]) if record.get("reference_id") == identifier), None)


def inspect_reference(document: dict | None, state: dict | None,
                      snapshot: SourceSnapshot | None = None) -> dict:
    record = current_record(document)
    response = {"status": "missing", "reference": record, "is_current": False, "reasons": [],
                "state_revision": state.get("revision", 0) if state is not None else None,
                "history_count": len(document["records"]) if document else 0}
    if record is None:
        return response
    if document.get("withdrawn"):
        response.update(status="withdrawn", reasons=["explicitly_withdrawn"])
        return response
    reasons = []
    if state is None:
        reasons.append("state_missing")
    if snapshot is None:
        reasons.append("source_unavailable")
    else:
        if snapshot.sha256 != record["sha256"]:
            reasons.append("source_changed")
        if state is not None:
            try:
                geometry = canonical_geometry(state, snapshot.width, snapshot.height)
                if "review_scope" in record:
                    current_hash = geometry_sha256(reviewed_geometry(geometry, record["review_scope"]))
                    expected_hash = record.get("reviewed_geometry_sha256")
                else:
                    # Existing immutable records keep the historical binding.
                    current_hash, expected_hash = geometry_sha256(geometry), record["geometry_sha256"]
                if current_hash != expected_hash:
                    reasons.append("geometry_changed")
            except ReferenceError:
                reasons.append("invalid_current_geometry")
    response.update(status="stale" if reasons else "verified", is_current=not reasons, reasons=reasons)
    return response


def create_reference(path: Path, image_path: Path, image_name: str, state: dict,
                     snapshot: SourceSnapshot, *, annotator: str, group_id: str | None,
                     annotation_context: dict | None = None, review_scope: dict | None = None) -> dict:
    """Append an explicit attestation without modifying the editable state."""
    geometry = canonical_geometry(state, snapshot.width, snapshot.height)
    scope = canonical_review_scope(review_scope if review_scope is not None else {
        "colony_count_reviewed": True, "colony_center_points_reviewed": True, "plate_crop_reviewed": False})
    notes = state.get("notes", "")
    if not isinstance(notes, str):
        raise ReferenceError("state notes must be text")
    document = load_document(path) or {"schema_version": 1, "records": [], "events": []}
    now = datetime.now(timezone.utc).isoformat()
    record = {"schema_version": 1, "reference_id": str(uuid4()), "verified": True,
              "human_confirmed": True, "annotator": annotator, "group_id": group_id,
              "notes": notes,
              "path": image_name, "sha256": snapshot.sha256,
              "count": len(geometry["detections_geometry"]),
              "points": [mark[:2] for mark in geometry["detections_geometry"]],
              **geometry, "plate_radius_px": geometry["plate"]["r"],
              "geometry_sha256": geometry_sha256(geometry),
              "review_scope": scope,
              "reviewed_geometry_sha256": geometry_sha256(reviewed_geometry(geometry, scope)),
              "image_revision": state.get("revision", 0), "verified_at_utc": now,
              "image_width": snapshot.width, "image_height": snapshot.height}
    if annotation_context is not None:
        record['annotation_context'] = json.loads(json.dumps(annotation_context, allow_nan=False))
    document["records"].append(record)
    document["events"].append({"event": "verified", "reference_id": record["reference_id"],
                               "at_utc": now, "annotator": annotator})
    document.update(current_reference_id=record["reference_id"], withdrawn=False)
    assert_source_unchanged(image_path, snapshot)
    atomic_write_json(path, document)
    return document


def withdraw_reference(path: Path) -> dict | None:
    document = load_document(path)
    record = current_record(document)
    if record is None or document.get("withdrawn"):
        return document
    document["withdrawn"] = True
    document["events"].append({"event": "withdrawn", "reference_id": record["reference_id"],
                               "at_utc": datetime.now(timezone.utc).isoformat()})
    atomic_write_json(path, document)
    return document
