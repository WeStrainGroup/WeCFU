"""Synthetic endpoint coverage for the local edge default; no model/photo inputs."""
import json

import pytest
from fastapi.testclient import TestClient

import wecfu.server.app as server
from wecfu.server import sam_runtime
from wecfu.server.web import build_web_app
from test_public_fusion_contract import BASE, app, initialized, sha, upload


def test_local_config_and_initialize_use_larger_edge_without_changing_sam(app, monkeypatch):
    application, _ = app
    monkeypatch.setattr(application.state.model_preview_manager.sam, 'capability',
                        lambda: {'available': True})
    with TestClient(application) as client:
        config = client.get('/api/config').json()
        assert config['default_params']['plate_inset'] == .95
        assert (config['default_params']['plate_inset'] - .5) / .5 == pytest.approx(.9)
        assert config['default_params']['min_value'] == 200
        assert config['default_params']['max_saturation'] == 100
        assert config['default_model'] == sam_runtime.ENGINE
        assert sam_runtime.PLATE_INSET == .95 and sam_runtime.COMPONENT_PARAMS['plate_inset'] == .95
        upload(client); state = initialized(client)
        assert {key:state['params'][key] for key in config['default_params']} == config['default_params']
        assert state['counted'] is False and state['detections'] == []


@pytest.mark.parametrize('explicit_inset', [None, .87])
def test_classical_run_uses_new_default_but_honors_explicit_custom_inset(app, monkeypatch, explicit_inset):
    application, _ = app
    for method in ('predict_sam', 'predict_fusion', 'predict'):
        monkeypatch.setattr(application.state.model_preview_manager, method,
                            lambda *a, **k: pytest.fail('Classical request must never invoke a model'))
    with TestClient(application) as client:
        raw = upload(client); state = initialized(client)
        response = client.post(BASE+'/run', params={
            'engine':server._COMPONENT_ENGINE, 'expected_revision':state['revision'],
            'expected_image_sha256':sha(raw), 'protect_existing_edits':True,
        }, json=None if explicit_inset is None else {'plate_inset':explicit_inset})
        assert response.status_code == 200, response.text
        counted = response.json(); expected = .95 if explicit_inset is None else explicit_inset
        assert counted['counted'] is True and counted['count_model'] is None
        assert counted['count_engine'] == server._COMPONENT_ENGINE
        assert counted['params']['plate_inset'] == counted['count_params']['plate_inset'] == expected
        assert counted['count_params']['min_value'] == 200 and counted['count_params']['max_saturation'] == 100


def test_existing_saved_inset_is_not_rewritten_on_initialize(app):
    application, root = app
    with TestClient(application) as client:
        upload(client); state = initialized(client)
        state['params']['plate_inset'] = .88
        path = server._det_path(root, 'demo', 'plate.png')
        path.write_text(json.dumps(state)); before = path.read_bytes()
        assert initialized(client) == state
        assert path.read_bytes() == before


def test_web_config_initialize_and_classical_default_remain_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(server, 'detect_plate', lambda pixels: server.PlateCircle(60,50,40))
    monkeypatch.setattr('wecfu.pipeline.detect_plate', lambda pixels: server.PlateCircle(60,50,40))
    application = build_web_app(tmp_path/'sessions')
    with TestClient(application, base_url='https://testserver') as client:
        config = client.get('/api/config').json()
        assert config['default_params']['plate_inset'] == .82
        assert config['default_model'] is None and config['default_count_engine'] == 'baseline'
        raw = upload(client); state = initialized(client)
        assert state['params']['plate_inset'] == .82
        response = client.post(BASE+'/run', params={'engine':'baseline',
            'expected_revision':state['revision'], 'expected_image_sha256':sha(raw)})
        assert response.status_code == 200
        assert response.json()['count_params']['plate_inset'] == .82
