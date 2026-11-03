"""Synthetic public input/candidate tests. No model, private data or network."""
import copy
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

import wecfu.server.app as server
from wecfu.server import fusion_runtime_v2 as fusion, model_preview, source_views
from wecfu.server.fusion_dino import fusion_math_v2 as math_v2
from wecfu.server.web import build_web_app

BASE = '/api/batch/demo/image/plate.png'


def picture(value=150):
    pixels = np.full((100, 120, 3), value, np.uint8)
    cv2.circle(pixels, (60, 50), 8, (240, 240, 240), -1)
    ok, encoded = cv2.imencode('.png', pixels)
    assert ok
    return encoded.tobytes()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(server, 'detect_plate', lambda pixels: server.PlateCircle(60, 50, 40))
    monkeypatch.setattr('wecfu.pipeline.detect_plate', lambda pixels: server.PlateCircle(60, 50, 40))
    root = tmp_path / 'workspace'
    app = server.build_app(lambda: root)
    return app, root


def upload(client, *, view='main', raw=None, name='plate.png'):
    raw = picture() if raw is None else raw
    response = client.post('/api/upload', data={'batch': 'demo', 'view': view}, files={'files': (name, raw, 'image/png')})
    assert response.status_code == 200, response.text
    return raw


def initialized(client):
    response = client.post(BASE+'/initialize', json={'mode': 'auto'})
    assert response.status_code == 200, response.text
    return response.json()


def preview_request(state, raw):
    return {'engine': server.sam_runtime.ENGINE, 'expected_revision': state['revision'],
            'expected_image_sha256': sha(raw), 'model_params': {}}


def fake_provenance(raw, plate, view):
    return dict(model_sha256=fusion.MODEL_SHA256, filter_artifact_sha256=fusion.FILTER_SHA256,
                sam_model_sha256=server.sam_runtime.MODEL_SHA256,
                dino_model_sha256=fusion.dino_contract.CHECKPOINT_SHA,
                detector_contract_sha256='a'*64, recipe_id=fusion.RECIPE_ID,
                image_sha256=sha(raw), plate_inset=.95, automatic_plate=copy.deepcopy(plate),
                raw_count=1, candidate_count=1, d0_count=1, supplemental_count=0, raw_dino_count=0,
                annotation_kind=fusion.ANNOTATION_KIND, source_view=view,
                feature_projection=list(math_v2.KEEP), coordinate_method='raw_DINO_unchanged',
                D0_exclusion_fraction=.025, DINO_dedup_fraction=.005, ROI_max_radial=.95)


def install_fake_predict(app, monkeypatch, *, callback=None):
    manager = app.state.model_preview_manager
    def predict(raw, plate, digest, width, height, view, **kwargs):
        assert digest == sha(raw) and width == 120 and height == 100
        assert kwargs['engine'] == fusion.ENGINE
        if callback:
            callback()
        marks = [{'id': 1, 'cx': 60., 'cy': 50., 'r': 8., 'score': .9, 'accepted': True, 'source': 'cv'}]
        return marks, 1, fake_provenance(raw, server.asdict(plate), view)
    monkeypatch.setattr(manager, 'predict_fusion', predict)
    def sam_predict(raw, plate, digest):
        assert digest == sha(raw)
        if callback:
            callback()
        return [{'id': 1, 'cx': 60., 'cy': 50., 'r': 8., 'score': .9, 'accepted': True, 'source': 'cv'}], 1
    monkeypatch.setattr(manager, 'predict_sam', sam_predict)
    return manager


@pytest.mark.parametrize('view', ['main', 'blank', 'back', 'unknown'])
def test_upload_declares_exact_bytes_and_does_not_create_review(app, view):
    application, root = app
    with TestClient(application) as client:
        raw = upload(client, view=view)
        assert client.get(BASE+'/source_view').json() == {'view': view, 'declared': True, 'source_sha256': sha(raw)}
        row = client.get('/api/batch/demo/images').json()['images'][0]
        assert row['source_view'] == view and row['source_view_declared'] is True
        assert row['reviewed'] is False and row['processed'] is False
        assert not (root/'runs').exists()
        assert not (root/'references').exists()


def test_path_import_default_unknown_is_unified_contract(app, tmp_path):
    application, root = app
    source = tmp_path/'looks_like_back.png'; source.write_bytes(picture())
    with TestClient(application) as client:
        r = client.post('/api/ingest', json={'paths': [str(source)], 'batch': 'demo'})
        assert r.status_code == 200
        url = '/api/batch/demo/image/looks_like_back.png/source_view'
        assert client.get(url).json()['view'] == 'unknown'  # Unified import never invents a view.
        r = client.post('/api/ingest', json={'paths': [str(source)], 'batch': 'other', 'view': 'back'})
        assert r.status_code == 200
        assert client.get('/api/batch/other/image/looks_like_back.png/source_view').json()['view'] == 'back'


def test_unknown_existing_image_and_replacement_cannot_inherit_declaration(app):
    application, root = app
    image = root/'inputs/demo/plate.png'; image.parent.mkdir(parents=True); image.write_bytes(picture())
    with TestClient(application) as client:
        assert client.get(BASE+'/source_view').json()['declared'] is False
        assert client.post(BASE+'/source_view', json={'source_sha256': sha(picture()), 'view': 'main'}).status_code == 200
        sidecar = root/'ui-metadata/source-views/demo/plate.png.json'
        before = sidecar.read_bytes()
        image.write_bytes(picture(70))
        assert client.get(BASE+'/source_view').json() == {'view': 'unknown', 'declared': False, 'source_sha256': sha(picture(70))}
        assert client.post(BASE+'/source_view', json={'source_sha256': sha(picture()), 'view': 'blank'}).status_code == 409
        assert sidecar.read_bytes() == before


def test_view_declaring_idempotent_preserves_state_and_rejects_extra_or_symlink(app, tmp_path):
    application, root = app
    with TestClient(application) as client:
        raw = upload(client); state = initialized(client)
        files = {str(p.relative_to(root)): p.read_bytes() for p in (root/'runs').rglob('*') if p.is_file()}
        body = {'source_sha256': sha(raw), 'view': 'main'}
        sidecar = root/'ui-metadata/source-views/demo/plate.png.json'; before = sidecar.stat().st_mtime_ns
        assert client.post(BASE+'/source_view', json=body).status_code == 200
        assert sidecar.stat().st_mtime_ns == before
        assert client.post(BASE+'/source_view', json={**body, 'reviewed': True}).status_code == 422
        assert client.post(BASE+'/source_view', json={**body, 'view': 'invalid'}).status_code == 422
        sidecar.unlink(); protected = tmp_path/'do-not-write.json'; protected.write_bytes(b'protected')
        sidecar.symlink_to(protected)
        assert client.post(BASE+'/source_view', json=body).status_code == 409
        assert protected.read_bytes() == b'protected'
        assert client.get(BASE+'/detections').json() == state
        assert {str(p.relative_to(root)): p.read_bytes() for p in (root/'runs').rglob('*') if p.is_file()} == files


def test_existing_valid_declared_view_takes_precedence_over_import_default(tmp_path):
    image = tmp_path/'image.png'; image.write_bytes(picture())
    source_views.declare(tmp_path, 'demo', 'image.png', image, 'back')
    result = source_views.declare(tmp_path, 'demo', 'image.png', image, 'main', preserve_existing=True)
    assert result['view'] == 'back'


@pytest.mark.parametrize('view', ['unknown', 'back'])
def test_old_fusion_request_never_calls_model_or_traditional(app, monkeypatch, view):
    application, root = app
    def forbidden(*args, **kwargs):
        pytest.fail('unsupported view must not run a model or fallback')
    monkeypatch.setattr(application.state.model_preview_manager, 'predict_fusion', forbidden)
    monkeypatch.setattr(server, 'process_image', forbidden)
    with TestClient(application) as client:
        raw = upload(client, view=view); state = initialized(client)
        assert client.post(BASE+'/model-preview', json={**preview_request(state, raw), 'engine': fusion.ENGINE}).status_code == 409
        assert client.post(BASE+'/run').status_code == 422  # Custom algorithm must be explicit.
        assert client.post('/api/batch/demo/run').status_code == 422
        assert client.get(BASE+'/detections').json() == state


def test_model_unavailable_has_no_fallback(app, monkeypatch):
    application, root = app
    manager = application.state.model_preview_manager
    def missing(*args, **kwargs):
        raise model_preview.PreviewError(503, 'SAM unavailable; no fallback was run')
    monkeypatch.setattr(manager, 'predict_sam', missing)
    monkeypatch.setattr(server, 'process_image', lambda *a, **k: pytest.fail('fallback prohibited'))
    with TestClient(application) as client:
        raw = upload(client); state = initialized(client)
        response = client.post(BASE+'/model-preview', json=preview_request(state, raw))
        assert response.status_code == 503 and 'no fallback' in response.json()['detail']
        assert not manager._candidates
        assert client.get(BASE+'/detections').json() == state


def test_view_change_during_preview_is_rejected(app, monkeypatch):
    application, root = app
    image = root/'inputs/demo/plate.png'
    install_fake_predict(application, monkeypatch, callback=lambda: source_views.declare(root, 'demo', 'plate.png', image, 'blank'))
    with TestClient(application) as client:
        raw = upload(client); state = initialized(client)
        response = client.post(BASE+'/model-preview', json=preview_request(state, raw))
        assert response.status_code == 409
        assert not application.state.model_preview_manager._candidates


def test_view_change_before_adoption_is_rejected(app, monkeypatch):
    application, root = app
    install_fake_predict(application, monkeypatch)
    with TestClient(application) as client:
        raw = upload(client); state = initialized(client)
        response = client.post(BASE+'/model-preview', json=preview_request(state, raw))
        assert response.status_code == 200, response.text
        candidate = response.json()
        assert client.post(BASE+'/source_view', json={'view': 'blank', 'source_sha256': sha(raw)}).status_code == 200
        response = client.post(BASE+'/model-preview/apply', json={'candidate_id': candidate['candidate_id'],
            'expected_revision': state['revision'], 'expected_image_sha256': sha(raw), 'request_id': 'synthetic-apply', 'replace_all': True})
        assert response.status_code == 409, response.text
        assert client.get(BASE+'/detections').json() == state


def test_web_preview_and_view_are_workspace_owned(tmp_path, monkeypatch):
    monkeypatch.setattr(server, 'detect_plate', lambda pixels: server.PlateCircle(60, 50, 40))
    app = build_web_app(tmp_path/'sessions'); install_fake_predict(app, monkeypatch)
    with TestClient(app, base_url='https://testserver') as one, TestClient(app, base_url='https://testserver') as two:
        raw = upload(one); upload(two, view='blank')
        a = initialized(one); b = initialized(two)
        r = one.post(BASE+'/model-preview', json=preview_request(a, raw))
        assert r.status_code == 200, r.text
        candidate = r.json()
        response = two.post(BASE+'/model-preview/apply', json={'candidate_id': candidate['candidate_id'],
            'expected_revision': b['revision'], 'expected_image_sha256': sha(raw), 'request_id': 'cross-workspace', 'replace_all': True})
        assert response.status_code == 409, response.text
        assert one.get(BASE+'/source_view').json()['view'] == 'main'
        assert two.get(BASE+'/source_view').json()['view'] == 'blank'
        assert one.post('/api/ingest', json={'paths': ['/never/read'], 'view': 'main'}).status_code == 403
        assert one.get(BASE+'/raw?reference_context=true').status_code == 403


def test_default_capability_and_busy_guard_never_load_models(app, monkeypatch, tmp_path):
    application, _ = app
    monkeypatch.setattr(fusion, 'AUTHORIZATION', tmp_path/'missing.json')
    with TestClient(application) as client:
        cfg = client.get('/api/config').json()
        assert cfg['default_count_engine'] == server._COMPONENT_ENGINE and cfg['default_model'] == server.sam_runtime.ENGINE
        assert cfg['refinement_model'] == server.sam_runtime.ENGINE
        assert cfg['default_model_fallback'] is False and cfg['internal'] is False
        assert cfg['models']['fusion_v2']['available'] is False
        assert cfg['models']['fusion_v2']['fallback'] is False
        assert cfg['models']['fusion']['available'] is False
        assert cfg['experimental_models']['cfucounter']['available'] is False
    manager = application.state.model_preview_manager
    assert manager.max_candidates == 16 and manager.ttl_seconds == 300
    model_preview._INFERENCE_SLOT.acquire()
    try:
        with pytest.raises(model_preview.PreviewError) as exc:
            manager.predict_fusion(b'', None, 'a'*64, 1, 1, 'main')
        assert exc.value.status_code == 429
    finally:
        model_preview._INFERENCE_SLOT.release()


def test_public_filter_fixed_numeric_contract_and_parameter_pin():
    raw = fusion.FILTER.read_bytes(); artifact = json.loads(raw)
    assert sha(raw) == fusion.FILTER_SHA256
    model = artifact['model']; math_v2.validate_product_model(model)
    assert sha(json.dumps(model, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()) == fusion.MODEL_SHA256
    assert model['coefficients'] == [1.1231926543706234, -0.09664632800086811, -0.2669266445450061,
        0.13689872951097998, 1.5466408014474848, 0.6526734355382888, -0.11185394771135333,
        0.13047756971455005, 0.0, 0.0]
    assert model['intercept'] == -0.9985323543984218 and model['threshold'] == .75
    assert not any(k.startswith('source_') or 'training' in k or 'round' in k for k in model)
    assert set(artifact) == {'schema_version', 'recipe_id', 'model'}
    # Independent scalar logit for one finite, and one declared-missing, row.
    import math
    rows = []
    for i, values in enumerate(([.6, -6., .2, .4, 1, .7, .2, .1, .05, -.1, 1, 1],
                                [.7, -5., -.1, None, 0, .2, None, None, None, None, 1, 1])):
        rows.append({'features': list(values), 'eligible': True, 'occurrence_id': str(i), 'path': 'synthetic',
            'sha256': 'a'*64, 'group': 'main', 'query_index': i, 'selection_rank': i, 'original_center': [5., 6.]})
    output = math_v2.predict_numeric10(rows, model)
    for row, result in zip(rows, output):
        values = [row['features'][i] for i in model['feature_projection']]; prep = model['preprocessing']
        z = model['intercept'] + sum(w*((prep['medians'][i] if v is None else v)-prep['means'][i])/prep['scales'][i]
                                    for i, (w, v) in enumerate(zip(model['coefficients'], values)))
        p = 1/(1+math.exp(-z))
        assert result['logit'] == pytest.approx(z, abs=1e-12)
        assert result['probability'] == pytest.approx(p, abs=1e-12)
        assert result['accepted'] == (p >= .75)


def test_product_manifest_verifies_fixed_sources_and_rejects_omission(tmp_path, monkeypatch):
    authority = json.loads(fusion.AUTHORIZATION.read_text())
    source = tmp_path/'product.json'; source.write_text(json.dumps(authority))
    checkpoint = tmp_path/'synthetic-model-file'; checkpoint.write_bytes(b'ab')
    monkeypatch.setattr(fusion, 'AUTHORIZATION', source)
    monkeypatch.setattr(fusion.dino_contract, 'verify_contract', lambda pin: {})
    monkeypatch.setattr(fusion.dino_contract, 'CHECKPOINT', checkpoint)
    monkeypatch.setattr(fusion.dino_contract, 'CHECKPOINT_BYTES', 2)
    provider = fusion.LocalFusionProvider(web_mode=True)
    monkeypatch.setattr(provider.sam, 'require_available', lambda: None)
    assert provider.require_available()[0] == authority
    authority['source_files_sha256'].pop('fusion_worker_v2.py')
    source.write_text(json.dumps(authority))
    with pytest.raises(fusion.RuntimeUnavailable, match='Complete Fusion'):
        provider.require_available()


def test_changed_model_artifact_rejected_before_prediction(tmp_path, monkeypatch):
    artifact = json.loads(fusion.FILTER.read_text()); artifact['model']['coefficients'][0] += .01
    changed = tmp_path/'changed.json'; changed.write_text(json.dumps(artifact))
    monkeypatch.setattr(fusion, 'FILTER', changed)
    monkeypatch.setattr(fusion.dino_contract, 'verify_contract', lambda pin: {})
    provider = fusion.LocalFusionProvider()
    with pytest.raises(fusion.RuntimeUnavailable, match='missing/changed'):
        provider.require_available()


def test_candidate_storage_ttl_and_count_bound(app):
    application, _ = app; manager = application.state.model_preview_manager
    state = {'plate': {'cx': 1., 'cy': 1., 'r': 1.}, 'revision': 0}
    identifiers = [manager.create_candidate(('workspace', 'batch', 'image'), state, 'a'*64,
        {}, [], 0, 0.)['candidate_id'] for _ in range(17)]
    assert len(manager._candidates) == 16
    with pytest.raises(model_preview.PreviewError) as expired:
        manager.candidate(identifiers[0], ('workspace', 'batch', 'image'))
    assert expired.value.status_code == 410
    deadline = max(v['deadline'] for v in manager._candidates.values())
    manager._clock = lambda: deadline+1
    with pytest.raises(model_preview.PreviewError) as expired:
        manager.candidate(identifiers[-1], ('workspace', 'batch', 'image'))
    assert expired.value.status_code == 410 and not manager._candidates
