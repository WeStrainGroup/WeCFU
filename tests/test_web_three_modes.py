"""The three public modes share one contract; synthetic fixtures, no model inference."""
import json

import pytest
from fastapi.testclient import TestClient

import wecfu.server.app as server
from wecfu.server.web import SESSION_COOKIE, build_web_app
from test_public_fusion_contract import BASE, initialized, sha, upload
from test_practical_recognition_policy import install_sam, sam_request, apply_request


@pytest.fixture
def web_application(tmp_path, monkeypatch):
    monkeypatch.setattr(server, 'detect_plate', lambda _: server.PlateCircle(60, 50, 40))
    monkeypatch.setattr('wecfu.pipeline.detect_plate', lambda _: server.PlateCircle(60, 50, 40))
    sessions = tmp_path / 'sessions'
    return build_web_app(sessions), sessions


def root_for(sessions, client):
    return sessions / client.cookies.get(SESSION_COOKIE)


def saved(root):
    return server._det_path(root, 'demo', 'plate.png')


@pytest.mark.parametrize('available', [False, True])
def test_web_declares_ultra_without_silent_fallback_and_improved_lite(web_application, monkeypatch, available):
    application, _ = web_application
    manager = application.state.model_preview_manager
    monkeypatch.setattr(manager.sam, 'capability', lambda: {'available': available})
    for method in ('predict', 'predict_sam', 'predict_fusion'):
        monkeypatch.setattr(manager, method, lambda *a, **kw: pytest.fail('Config must not infer'))
    with TestClient(application, base_url='https://testserver') as client:
        config = client.get('/api/config').json()
    assert config['web_mode'] is True
    assert config['default_model'] == server.sam_runtime.ENGINE
    assert config['models']['sam2']['available'] is available
    assert config['default_model_fallback'] is False
    assert config['builtin_algorithms'] == ['baseline', server._COMPONENT_ENGINE]
    assert config['default_count_engine'] == server._COMPONENT_ENGINE
    assert config['default_params'] == server._INTERNAL_DEFAULT_PARAMS
    assert 'refinement_model' not in config
    assert config['recognition_policy_version'] == 'unified-ultra-lite-custom-v2'


@pytest.mark.parametrize('custom', [False, True])
def test_web_lite_and_custom_use_exact_selected_recipe_without_any_model(web_application, monkeypatch, custom):
    application, _ = web_application
    for method in ('predict', 'predict_sam', 'predict_fusion'):
        monkeypatch.setattr(application.state.model_preview_manager, method,
                            lambda *a, **kw: pytest.fail('Lite/Custom must not infer a model'))
    with TestClient(application, base_url='https://testserver') as client:
        raw = upload(client, view='unknown'); state = initialized(client)
        params = dict(server._INTERNAL_DEFAULT_PARAMS)
        if custom:
            params.update(min_value=173, max_saturation=92, plate_inset=.91)
        response = client.post(BASE + '/run', params={'engine':server._COMPONENT_ENGINE,
            'expected_revision':state['revision'], 'expected_image_sha256':sha(raw),
            'only_unrecognized':True, 'protect_existing_edits':True}, json=params)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result['count_engine'] == server._COMPONENT_ENGINE
        assert result['count_model'] is None
        expected_params = server.asdict(server.SegmentParams(**params))
        assert result['count_params'] == expected_params
        assert result['counted'] is True and result['reviewed'] is False
        # Ordinary edits/Undo preserve the advertised improved-algorithm provenance on Web.
        body = {key:result[key] for key in ('detections','plate','mode','machine_count_initial',
            'notes','plate_manual','reviewed','params','counted','count_params','count_engine','count_model')}
        body['expected_revision'] = result['revision']
        body['notes'] = 'synthetic edited note'
        response = client.put(BASE + '/state', json=body)
        assert response.status_code == 200, response.text
        assert response.json()['count_engine'] == server._COMPONENT_ENGINE
        assert response.json()['count_params'] == expected_params


def test_web_ultra_batch_preview_adoption_is_bound_to_session_and_receipt(web_application, monkeypatch):
    application, sessions = web_application
    calls = install_sam(application, monkeypatch)
    with TestClient(application, base_url='https://testserver') as one, TestClient(application, base_url='https://testserver') as two:
        raw = upload(one, view='unknown'); upload(two, view='unknown')
        a, b = initialized(one), initialized(two)
        before_one = saved(root_for(sessions, one)).read_bytes()
        before_two = saved(root_for(sessions, two)).read_bytes()
        response = one.post(BASE+'/model-preview', json={**sam_request(a, raw), 'only_unrecognized':True})
        assert response.status_code == 200, response.text
        candidate = response.json()
        assert len(calls) == 1
        assert saved(root_for(sessions, one)).read_bytes() == before_one
        assert candidate['engine'] == server.sam_runtime.ENGINE
        body = {**apply_request(candidate, a, raw), 'only_unrecognized':True}
        foreign = two.post(BASE+'/model-preview/apply', json=body)
        assert foreign.status_code == 409, foreign.text
        assert saved(root_for(sessions, two)).read_bytes() == before_two
        result = one.post(BASE+'/model-preview/apply', json=body)
        assert result.status_code == 200, result.text
        result = result.json()
        assert result['count_engine'] == server.sam_runtime.ENGINE
        assert result['counted'] is True and result['reviewed'] is False
        assert result['detections'] == candidate['detections']
        receipt = result['_model_preview_apply']
        assert receipt['request'] == body
        assert receipt['applied_revision'] == a['revision'] + 1
        assert one.post(BASE+'/model-preview/apply', json=body).json() == result
        again = one.post(BASE+'/model-preview', json={**sam_request(result, raw), 'only_unrecognized':True})
        assert again.status_code == 409 and 'already_counted' in again.json()['detail']
        assert len(calls) == 1
        assert one.get(BASE+'/detections').json() == result
        assert not server._reference_path(root_for(sessions, one), 'demo', 'plate.png').exists()


@pytest.mark.parametrize('phase', ['before_preview','during_preview','before_adoption'])
def test_web_ultra_batch_preserves_human_work_at_every_stage(web_application, monkeypatch, phase):
    application, sessions = web_application
    with TestClient(application, base_url='https://testserver') as client:
        raw = upload(client); state = initialized(client); root = root_for(sessions, client)
        def add_note():
            current = json.loads(saved(root).read_bytes())
            current['notes'] = 'synthetic concurrent edit'
            saved(root).write_text(json.dumps(current))
        calls = install_sam(application, monkeypatch, add_note if phase == 'during_preview' else None)
        if phase == 'before_preview':
            add_note()
        response = client.post(BASE+'/model-preview', json={**sam_request(state, raw), 'only_unrecognized':True})
        if phase == 'before_adoption':
            assert response.status_code == 200, response.text
            add_note()
            response = client.post(BASE+'/model-preview/apply', json={
                **apply_request(response.json(), state, raw), 'only_unrecognized':True})
        assert response.status_code == 409, response.text
        assert len(calls) == (0 if phase == 'before_preview' else 1)
        preserved = json.loads(saved(root).read_bytes())
        assert preserved == {**state, 'notes':'synthetic concurrent edit'}
        assert not (root/'runs/demo/model_preview_recovery').exists()


def test_web_ultra_failure_is_not_saved_as_lite_or_zero(web_application, monkeypatch):
    application, sessions = web_application
    install_sam(application, monkeypatch)
    def fail(*args, **kwargs):
        raise server.model_preview.PreviewError(503, 'Synthetic unavailable SAM')
    monkeypatch.setattr(application.state.model_preview_manager, 'predict_sam', fail)
    with TestClient(application, base_url='https://testserver') as client:
        raw = upload(client); state = initialized(client); path = saved(root_for(sessions, client))
        before = path.read_bytes()
        response = client.post(BASE+'/model-preview', json={**sam_request(state, raw), 'only_unrecognized':True})
        assert response.status_code == 503
        assert path.read_bytes() == before
        assert application.state.model_preview_manager._candidates == {}
