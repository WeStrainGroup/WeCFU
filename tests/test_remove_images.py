"""Batch UI uses existing per-image DELETE: verify isolation with generated files only."""
import hashlib
from pathlib import Path

import cv2
import numpy as np
from fastapi.testclient import TestClient
import wecfu.server.app as server


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_removing_selected_links_keeps_originals_and_unchosen_records(tmp_path, monkeypatch):
    photos = tmp_path / 'originals'
    photos.mkdir()
    for name in ('one.png', 'two.png', 'keep.png'):
        assert cv2.imwrite(str(photos / name), np.full((80, 80, 3), 140, np.uint8))
    original = {p.name: digest(p) for p in photos.iterdir()}
    root = tmp_path / 'workspace'
    monkeypatch.setattr(server, 'detect_plate', lambda _: server.PlateCircle(40, 40, 35))
    app = server.build_app(lambda: root)
    with TestClient(app) as client:
        imported = client.post('/api/ingest', json={'paths': [str(photos)], 'view': 'main', 'batch': 'sample'})
        assert imported.status_code == 200, imported.text
        for name in original:
            assert (root / 'inputs/sample' / name).is_symlink()
            assert client.post(f'/api/batch/sample/image/{name}/initialize', json={'mode':'auto'}).status_code == 200
        keep = root / 'runs/sample/detections/keep.png.json'
        saved = keep.read_bytes()
        for name in ('one.png', 'two.png'):
            result = client.delete(f'/api/batch/sample/image/{name}')
            assert result.status_code == 200, result.text
            assert not (root / 'inputs/sample' / name).exists()
            assert not (root / 'runs/sample/detections' / f'{name}.json').exists()
        assert [row['name'] for row in client.get('/api/batch/sample/images').json()['images']] == ['keep.png']
        assert keep.read_bytes() == saved
        assert {p.name:digest(p) for p in photos.iterdir()} == original
        assert client.delete('/api/batch/sample/image/one.png').status_code == 404


def test_delete_all_uploaded_copies_leaves_empty_list_and_original_files_unchanged(tmp_path, monkeypatch):
    original = tmp_path / 'source.png'
    assert cv2.imwrite(str(original), np.full((80,80,3), 100, np.uint8))
    raw = original.read_bytes()
    root = tmp_path / 'workspace'
    monkeypatch.setattr(server, 'detect_plate', lambda _: server.PlateCircle(40,40,35))
    with TestClient(server.build_app(lambda: root)) as client:
        result = client.post('/api/upload', data={'batch':'sample','view':'main'},
                             files=[('files',('one.png',raw,'image/png')),('files',('two.png',raw,'image/png'))])
        assert result.status_code == 200, result.text
        for name in ('one.png','two.png'):
            assert client.delete(f'/api/batch/sample/image/{name}').status_code == 200
        assert client.get('/api/batch/sample/images').json()['images'] == []
        assert original.read_bytes() == raw
