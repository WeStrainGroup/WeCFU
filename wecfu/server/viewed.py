"""Source-bound UI browsing state, never an edit or human attestation.

The API caller holds the workspace/image lock. Image symlinks are intentional
for local imports; UI metadata directories and files must not be symlinks.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile


class ViewedError(ValueError):
    """Browsing metadata cannot safely be read or saved."""


class SourceChanged(ViewedError):
    """The source is no longer the image that the browser displayed."""


def _component(value: str) -> str:
    if (type(value) is not str or not value or value in {".", ".."}
            or any(c in value for c in ("/", "\\", "\0"))):
        raise ViewedError("invalid browsing metadata path")
    return value


def _fingerprint(value) -> tuple:
    return (value.st_dev, value.st_ino, value.st_mode, value.st_size,
            value.st_mtime_ns, value.st_ctime_ns)


def _source_identity(image: Path) -> tuple[str, tuple]:
    """Hash exact original bytes without decoding or loading any model."""
    with image.open("rb") as stream:
        before = _fingerprint(os.fstat(stream.fileno()))
        if not stat.S_ISREG(before[2]):
            raise ViewedError("source image must be a regular file")
        digest = hashlib.sha256()
        while block := stream.read(1024 * 1024):
            digest.update(block)
        if _fingerprint(os.fstat(stream.fileno())) != before:
            raise SourceChanged("source image changed; reload the displayed image")
    _assert_source_unchanged(image, before)
    return digest.hexdigest(), before


def _assert_source_unchanged(image: Path, fingerprint: tuple) -> None:
    # Compare handles with handles. On CPython 3.12 for Windows, path stat's
    # ctime is creation time while fstat's ctime is metadata change time.
    # Reopening the name also detects replacement/retargeting of the path.
    with image.open("rb") as current:
        if _fingerprint(os.fstat(current.fileno())) != fingerprint:
            raise SourceChanged("source image changed; reload the displayed image")


def _sidecar(root: Path, batch: str, name: str, *, create: bool = False) -> Path:
    directory = root.resolve()
    for part in ("ui-metadata", "viewed", _component(batch)):
        directory = directory / part
        if directory.is_symlink():
            raise ViewedError("browsing metadata directory must not be a symlink")
        if create:
            directory.mkdir(exist_ok=True)
        if directory.exists() and not directory.is_dir():
            raise ViewedError("invalid browsing metadata directory")
    path = directory / f"{_component(name)}.json"
    if path.is_symlink():
        raise ViewedError("browsing metadata must not be a symlink")
    return path


def _record(root: Path, batch: str, name: str, source_sha256: str) -> dict:
    return {"schema_version": 1, "kind": "ui_browsed_not_human_review",
            "workspace": str(root.resolve()), "batch": batch, "image": name,
            "source_sha256": source_sha256, "viewed": True}


def _read(path: Path):
    if path.exists() and not path.is_file():
        raise ViewedError("browsing metadata must be a regular file")
    try:
        with path.open("rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ViewedError("browsing metadata must be a regular file")
            payload = stream.read(8193)
        if len(payload) > 8192:
            return None
        return json.loads(payload)
    except (FileNotFoundError, ValueError, UnicodeError):
        return None


def is_viewed(root: Path, batch: str, name: str, image: Path) -> bool:
    """A missing, malformed or stale sidecar never implies successful viewing."""
    record = _read(_sidecar(root, batch, name))
    if record is None:
        return False
    digest, _ = _source_identity(image)
    return (type(record) is dict and record.get("viewed") is True
            and type(record.get("schema_version")) is int
            and record == _record(root, batch, name, digest))


def mark_viewed(root: Path, batch: str, name: str, image: Path, source_sha256: str) -> dict:
    if (type(source_sha256) is not str or len(source_sha256) != 64
            or any(c not in "0123456789abcdef" for c in source_sha256)):
        raise ViewedError("invalid source SHA256")
    # Validate names before any read or directory creation, including direct use.
    _component(batch)
    _component(name)
    digest, fingerprint = _source_identity(image)
    if digest != source_sha256:
        raise SourceChanged("source differs from the displayed image; reload it")
    record = _record(root, batch, name, digest)
    path = _sidecar(root, batch, name)
    if _read(path) == record:
        _assert_source_unchanged(image, fingerprint)
        return {"viewed": True, "source_sha256": digest}
    path = _sidecar(root, batch, name, create=True)
    fd, temporary = tempfile.mkstemp(prefix=".viewed-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(record, stream, ensure_ascii=False, separators=(",", ":"))
        _assert_source_unchanged(image, fingerprint)
        _sidecar(root, batch, name)  # Recheck metadata links before publication.
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return {"viewed": True, "source_sha256": digest}
