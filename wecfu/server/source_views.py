"""User-declared image view, bound to exact bytes; never a human reference.

The caller holds the workspace/image lock. A name alone cannot authorize a
model input, and an old record is not inherited by a replacement image.
"""
from pathlib import Path
import json
import os
import tempfile
from . import viewed

VIEWS = ("main", "blank", "back", "unknown")
KIND = "user_declared_photo_view_not_human_review"


def _path(root, batch, name, create=False):
    directory = Path(root).resolve()
    for part in ("ui-metadata", "source-views", viewed._component(batch)):
        directory /= part
        if directory.is_symlink():
            raise viewed.ViewedError("source view directory must not be a symlink")
        if create:
            directory.mkdir(exist_ok=True)
        if directory.exists() and not directory.is_dir():
            raise viewed.ViewedError("invalid source view directory")
    path = directory / (viewed._component(name) + ".json")
    if path.is_symlink():
        raise viewed.ViewedError("source view metadata must not be a symlink")
    return path


def _record(root, batch, name, sha256, view):
    return {"schema_version": 1, "kind": KIND, "workspace": str(Path(root).resolve()),
            "batch": batch, "image": name, "source_sha256": sha256, "view": view}


def get(root, batch, name, image, *, expected_sha256=None):
    digest, _ = viewed._source_identity(Path(image))
    if expected_sha256 is not None and digest != expected_sha256:
        raise viewed.SourceChanged("Source differs from the displayed image; reload it")
    record = viewed._read(_path(root, batch, name))
    valid = (type(record) is dict and type(record.get("schema_version")) is int
             and record.get("view") in VIEWS
             and record == _record(root, batch, name, digest, record["view"]))
    return {"source_sha256": digest, "view": record["view"] if valid else "unknown",
            "declared": bool(valid)}


def declare(root, batch, name, image, view, *, expected_sha256=None, preserve_existing=False):
    if type(view) is not str or view not in VIEWS:
        raise viewed.ViewedError("Unknown photo view")
    viewed._component(batch); viewed._component(name)
    digest, fingerprint = viewed._source_identity(Path(image))
    if expected_sha256 is not None and digest != expected_sha256:
        raise viewed.SourceChanged("Source differs from the displayed image; reload it")
    current = viewed._read(_path(root, batch, name))
    valid = (type(current) is dict and type(current.get("schema_version")) is int
             and current.get("view") in VIEWS
             and current == _record(root, batch, name, digest, current["view"]))
    if valid and (preserve_existing or current["view"] == view):
        viewed._assert_source_unchanged(Path(image), fingerprint)
        return {"source_sha256": digest, "view": current["view"], "declared": True}
    record = _record(root, batch, name, digest, view)
    path = _path(root, batch, name, create=True)
    fd, temporary = tempfile.mkstemp(prefix=".source-view-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(record, stream, ensure_ascii=False, separators=(",", ":"))
        viewed._assert_source_unchanged(Path(image), fingerprint)
        _path(root, batch, name)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return {"source_sha256": digest, "view": view, "declared": True}
