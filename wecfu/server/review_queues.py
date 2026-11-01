"""Read-only, workspace-local lists for an explicitly selected review session."""
from __future__ import annotations

import json
from pathlib import Path
import re

from fastapi import HTTPException


def _text(value, label):
    if not isinstance(value, str) or not value.strip() or any(ord(char) < 32 and char not in '\n\t' for char in value):
        raise HTTPException(400, f"review queue {label} must be nonempty text")
    return value


def _component(value, label):
    value = _text(value, label)
    if value in {'.', '..'} or any(char in value for char in '/\\\0\n\t'):
        raise HTTPException(400, f"invalid review queue {label}")
    return value


def load_queue(root: Path, queue_id: str) -> dict:
    """Validate the complete manifest without creating files or directories."""
    if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', queue_id) is None:
        raise HTTPException(400, "invalid review queue id")
    directory = root / 'review-queues'
    path = directory / f'{queue_id}.json'
    if directory.is_symlink() or path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise HTTPException(400, "review queue must be a regular workspace-local manifest")
    try:
        payload = path.read_text(encoding='utf-8')
    except FileNotFoundError as exc:
        raise HTTPException(404, "review queue not found") from exc
    except (OSError, UnicodeError) as exc:
        raise HTTPException(400, "review queue cannot be read") from exc
    try:
        manifest = json.loads(payload)
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, "invalid review queue JSON") from exc
    if (not isinstance(manifest, dict) or type(manifest.get('schema_version')) is not int
            or manifest['schema_version'] != 1):
        raise HTTPException(400, "unsupported review queue schema")
    title = _text(manifest.get('title'), 'title')
    batch = _component(manifest.get('batch'), 'batch')
    policy = _text(manifest.get('policy'), 'policy')
    annotation_mode = manifest.get('annotation_mode', 'existing')
    if annotation_mode not in ('existing', 'manual_only', 'assisted_frozen'):
        raise HTTPException(400, "unsupported review queue annotation_mode")
    if annotation_mode == 'assisted_frozen' and manifest.get('engine') != 'sam2_cv_frozen_v1':
        raise HTTPException(400, "unsupported assisted review engine")
    raw_items = manifest.get('items')
    if not isinstance(raw_items, list) or not raw_items:
        raise HTTPException(400, "review queue requires a nonempty ordered items list")
    items, names = [], set()
    for item in raw_items:
        if not isinstance(item, dict):
            raise HTTPException(400, "invalid review queue item")
        name = _component(item.get('name'), 'image name')
        if name in names:
            raise HTTPException(400, "review queue image names must be unique")
        names.add(name)
        group_id = item.get('group_id')
        if group_id is not None:
            group_id = _text(group_id, 'group_id')
            if any(ord(char) < 32 for char in group_id):
                raise HTTPException(400, "invalid review queue group_id")
        validated = {'name': name, 'group_id': group_id}
        if 'context' in item:
            validated['context'] = _text(item['context'], 'item context')
        items.append(validated)
    result = {'id': queue_id, 'title': title, 'batch': batch, 'policy': policy,
              'annotation_mode': annotation_mode, 'items': items}
    if annotation_mode == 'assisted_frozen':
        result['engine'] = manifest['engine']
    return result


def annotation_mode_for_batch(root: Path, batch: str) -> str:
    """A manual-only queue protects its whole batch, including other API URLs.

    Read manifests on demand, so protection never depends on visiting the queue
    page first or on a client-supplied flag. Malformed/symlinked policy manifests
    fail closed; they must be repaired rather than silently dropping protection.
    Multiple queues for a batch cannot weaken an existing manual-only policy.
    """
    directory = root / 'review-queues'
    if directory.is_symlink():
        raise HTTPException(400, "review queue policies must be workspace-local")
    if not directory.exists():
        return 'existing'
    if not directory.is_dir():
        raise HTTPException(400, "review queue policy directory is invalid")
    modes = set()
    for path in sorted(directory.glob('*.json')):
        queue = load_queue(root, path.stem)
        if queue['batch'] == batch and queue['annotation_mode'] != 'existing':
            modes.add(queue['annotation_mode'])
    if len(modes) > 1:
        raise HTTPException(409, "conflicting review policies for the same batch")
    return next(iter(modes), 'existing')
