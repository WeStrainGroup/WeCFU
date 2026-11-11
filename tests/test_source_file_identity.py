"""Synthetic source-byte binding across Windows and POSIX file-stat semantics."""
import hashlib
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace

import cv2
from fastapi.testclient import TestClient
import numpy as np
import pytest

from wecfu import reference
from wecfu.server import app as server, source_views, viewed


def image_bytes(value=150):
    ok, encoded = cv2.imencode('.png', np.full((8, 9, 3), value, np.uint8))
    assert ok
    return encoded.tobytes()


@pytest.fixture
def different_path_and_handle_ctime(monkeypatch):
    """CPython Windows 3.12 keeps CreationTime in stat, ChangeTime in fstat.

    Exercise that documented source-code distinction on every CI platform,
    without discarding inode, mode, time or size changes in either API.
    """
    original = os.fstat

    def handle_stat(fd):
        result = original(fd)
        fields = {key: getattr(result, key) for key in dir(result) if key.startswith('st_')}
        fields['st_ctime_ns'] += 1_000_000
        fields['st_ctime'] += .001
        return SimpleNamespace(**fields)

    monkeypatch.setattr(os, 'fstat', handle_stat)


@pytest.mark.parametrize('method', ['upload', 'path', 'path-copy'])
def test_import_binds_exact_bytes_despite_path_handle_ctime_difference(
        tmp_path, monkeypatch, different_path_and_handle_ctime, method):
    root = tmp_path / 'workspace'
    source = tmp_path / '原始照片 空格.png'
    raw = image_bytes()
    source.write_bytes(raw)
    if method == 'path-copy':
        # Windows commonly denies symlink creation for ordinary desktop users.
        def no_symlinks(*args, **kwargs):
            raise OSError('synthetic Windows symlink privilege unavailable')
        monkeypatch.setattr(Path, 'symlink_to', no_symlinks)
    with TestClient(server.build_app(lambda: root)) as client:
        if method == 'upload':
            response = client.post('/api/upload', data={'batch': 'demo', 'view': 'unknown'},
                                   files={'files': (source.name, raw, 'image/png')})
        else:
            response = client.post('/api/ingest', json={'batch': 'demo', 'paths': [str(source)]})
        assert response.status_code == 200, response.text
        assert response.json()['names'] == [source.name]
        imported = root / 'inputs' / 'demo' / source.name
        assert imported.read_bytes() == raw == source.read_bytes()
        if method == 'path-copy':
            assert not imported.is_symlink()
        base = '/api/batch/demo/image/' + source.name
        expected = hashlib.sha256(raw).hexdigest()
        assert client.get(base + '/source_view').json() == {
            'source_sha256': expected, 'view': 'unknown', 'declared': True}
        assert client.post(base + '/viewed', json={'source_sha256': expected}).status_code == 200
        row = client.get('/api/batch/demo/images').json()['images'][0]
        assert row['viewed'] is True and row['reviewed'] is False
        assert not (root / 'references').exists()
        snapshot = reference.read_source_snapshot(imported)
        assert snapshot.sha256 == expected and snapshot.payload == raw
        reference.assert_source_unchanged(imported, snapshot)


@pytest.mark.skipif(sys.platform != 'win32', reason='real CPython/NTFS timestamp semantics')
def test_real_windows_file_after_write_and_rename_can_be_uploaded_and_bound(tmp_path):
    # Real operations, no stat mocks. Reproduce the upload's create/write/rename
    # sequence with a short gap so creation and change times cannot coincide.
    source = tmp_path / 'created.png'
    source.touch()
    time.sleep(.03)
    raw = image_bytes()
    source.write_bytes(raw)
    renamed = tmp_path / 'renamed.png'
    source.replace(renamed)
    with renamed.open('rb') as stream:
        handle_stat = os.fstat(stream.fileno())
    path_stat = renamed.stat()
    # Record actual observations for the Windows JUnit/captured-output evidence.
    print({'python': sys.version, 'path_ctime_ns': path_stat.st_ctime_ns,
           'handle_ctime_ns': handle_stat.st_ctime_ns,
           'birthtime_ns': getattr(path_stat, 'st_birthtime_ns', None)})
    root = tmp_path / 'workspace'
    root.mkdir()
    assert viewed._source_identity(renamed)[0] == hashlib.sha256(raw).hexdigest()
    snapshot = reference.read_source_snapshot(renamed)
    reference.assert_source_unchanged(renamed, snapshot)
    with TestClient(server.build_app(lambda: root)) as client:
        response = client.post('/api/upload', data={'batch': 'demo'},
                               files={'files': ('uploaded.png', raw, 'image/png')})
        assert response.status_code == 200, response.text
        response = client.post('/api/ingest', json={'batch': 'demo', 'paths': [str(renamed)]})
        assert response.status_code == 200, response.text


@pytest.mark.parametrize('kind', ['viewed', 'reference'])
def test_replaced_same_size_file_with_restored_mtime_is_rejected(tmp_path, kind):
    image = tmp_path / 'image.png'
    raw = image_bytes()
    image.write_bytes(raw)
    before = image.stat()
    if kind == 'viewed':
        _, identity = viewed._source_identity(image)
        check = lambda: viewed._assert_source_unchanged(image, identity)
        error = viewed.SourceChanged
    else:
        snapshot = reference.read_source_snapshot(image)
        check = lambda: reference.assert_source_unchanged(image, snapshot)
        error = reference.ReferenceChanged
    replacement = tmp_path / 'replacement.png'
    replacement.write_bytes(raw)  # Even identical bytes are a different source file.
    os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
    replacement.replace(image)
    assert image.stat().st_size == before.st_size
    assert image.stat().st_mtime_ns == before.st_mtime_ns
    with pytest.raises(error):
        check()


@pytest.mark.parametrize('kind', ['viewed', 'reference'])
def test_replacement_between_read_and_final_named_check_is_rejected(tmp_path, monkeypatch, kind):
    image = tmp_path / 'image.png'
    replacement = tmp_path / 'replacement.png'
    raw = image_bytes()
    image.write_bytes(raw)
    replacement.write_bytes(raw)
    stamp = image.stat()
    os.utime(replacement, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    original_open = Path.open
    used = False

    class ReplaceAfterRead:
        def __init__(self, stream):
            self.stream = stream
        def __enter__(self):
            return self.stream.__enter__()
        def __exit__(self, *args):
            outcome = self.stream.__exit__(*args)
            # Closing first also permits the replacement on Windows.
            replacement.replace(image)
            return outcome

    def open_then_replace(path, mode='r', *args, **kwargs):
        nonlocal used
        stream = original_open(path, mode, *args, **kwargs)
        if path == image and mode == 'rb' and not used:
            used = True
            return ReplaceAfterRead(stream)
        return stream

    monkeypatch.setattr(Path, 'open', open_then_replace)
    operation = viewed._source_identity if kind == 'viewed' else reference.read_source_snapshot
    error = viewed.SourceChanged if kind == 'viewed' else reference.ReferenceChanged
    with pytest.raises(error):
        operation(image)


@pytest.mark.parametrize('kind', ['viewed', 'reference'])
def test_in_place_change_is_rejected_without_weakening_change_time_checks(
        tmp_path, monkeypatch, different_path_and_handle_ctime, kind):
    image = tmp_path / 'image.png'
    raw = image_bytes()
    image.write_bytes(raw)
    if kind == 'viewed':
        _, identity = viewed._source_identity(image)
        check = lambda: viewed._assert_source_unchanged(image, identity)
        error = viewed.SourceChanged
    else:
        snapshot = reference.read_source_snapshot(image)
        check = lambda: reference.assert_source_unchanged(image, snapshot)
        error = reference.ReferenceChanged
    # Force only the handle's change time to move, leaving all other identity
    # fields equal: omitting ctime to work around Windows would miss this.
    original = os.fstat
    def changed(fd):
        value = original(fd)
        return SimpleNamespace(**{**vars(value), 'st_ctime_ns': value.st_ctime_ns + 1})
    monkeypatch.setattr(os, 'fstat', changed)
    with pytest.raises(error):
        check()


@pytest.mark.parametrize('method', ['upload', 'path'])
def test_failed_binding_rolls_back_new_import_and_preserves_existing_bytes(
        tmp_path, monkeypatch, method):
    root = tmp_path / 'workspace'
    directory = root / 'inputs' / 'demo'
    directory.mkdir(parents=True)
    raw = image_bytes()
    original = tmp_path / 'same.png'
    original.write_bytes(raw)
    existing = directory / original.name
    existing.write_bytes(b'previous imported bytes')
    source_views.declare(root, 'demo', existing.name, existing, 'main')
    metadata = root / 'ui-metadata' / 'source-views' / 'demo' / (existing.name + '.json')
    before_metadata = metadata.read_bytes()
    def fail_binding(*args, **kwargs):
        raise viewed.SourceChanged('synthetic concurrent change')
    monkeypatch.setattr(source_views, 'declare', fail_binding)
    with TestClient(server.build_app(lambda: root)) as client:
        if method == 'upload':
            response = client.post('/api/upload', data={'batch': 'demo'},
                                   files={'files': (original.name, raw, 'image/png')})
        else:
            response = client.post('/api/ingest', json={'batch': 'demo', 'paths': [str(original)]})
        assert response.status_code == 409
    assert original.read_bytes() == raw
    assert existing.read_bytes() == b'previous imported bytes'
    assert metadata.read_bytes() == before_metadata
    assert sorted(path.name for path in directory.iterdir()) == [existing.name]
    assert sorted(path.name for path in metadata.parent.iterdir()) == [metadata.name]
