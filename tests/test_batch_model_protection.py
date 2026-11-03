"""Synthetic classical batch-intent guards; no real photos or model inference."""
import copy
import json

import pytest
from fastapi.testclient import TestClient

import wecfu.server.app as server
from test_public_fusion_contract import BASE, app, initialized, sha, upload


PROTECTIONS = [
    ('already_counted', {'counted': True}),  # Also protects a recognized zero-count image.
    ('legacy_status_unknown', {'counted': None}),
    ('machine_count_history', {'machine_count_initial': 1}),
    ('existing_marks', {'detections': [{'id': 1, 'cx': 60., 'cy': 50., 'r': 4.,
                                      'source': 'cv', 'accepted': True, 'score': .8}]}),
    ('existing_marks', {'detections': [{'id': 1, 'cx': 60., 'cy': 50., 'r': 4.,
                                      'source': 'manual', 'accepted': True, 'score': 1.}]}),
    ('manual_mode', {'mode': 'manual'}),
    ('reviewed', {'reviewed': True}),
    ('notes', {'notes': 'Keep this synthetic note.'}),
    ('notes', {'notes': '   '}),  # Even whitespace is existing note content, not bulk permission.
    ('manual_plate', {'plate_manual': True}),
]


def state_bytes(root):
    return server._det_path(root, 'demo', 'plate.png').read_bytes()


def replace_synthetic_state(root, state):
    server._det_path(root, 'demo', 'plate.png').write_text(json.dumps(state))


def run_request(client, state, raw, *, base=BASE, engine=server._COMPONENT_ENGINE, **extra):
    return client.post(base + '/run', params={'engine': engine,
        'only_unrecognized': True, 'protect_existing_edits': True,
        'expected_revision': state['revision'], 'expected_image_sha256': sha(raw), **extra})


def forbid_models(application, monkeypatch):
    for method in ('predict_sam', 'predict_fusion', 'predict'):
        monkeypatch.setattr(application.state.model_preview_manager, method,
                            lambda *a, **k: pytest.fail('Classical default must not invoke models'))


@pytest.mark.parametrize('reason,changes', PROTECTIONS)
def test_classical_batch_protection_before_processing(app, monkeypatch, reason, changes):
    application, root = app; forbid_models(application, monkeypatch)
    monkeypatch.setattr(server, 'process_image', lambda *a, **k: pytest.fail('Protected state must not run'))
    with TestClient(application) as client:
        raw = upload(client); state = initialized(client)
        state.update(copy.deepcopy(changes)); replace_synthetic_state(root, state); before = state_bytes(root)
        response = run_request(client, state, raw)
        assert response.status_code == 409 and f'only_unrecognized: {reason};' in response.json()['detail']
        assert state_bytes(root) == before


@pytest.mark.parametrize('kind', ['current', 'withdrawn_history', 'dangling_symlink'])
def test_any_reference_presence_protects_without_parsing_or_writing(app, monkeypatch, kind):
    application, root = app
    monkeypatch.setattr(server, 'process_image', lambda *a, **k: pytest.fail('Protected reference must not run'))
    with TestClient(application) as client:
        raw = upload(client); state = initialized(client)
        reference = server._reference_path(root, 'demo', 'plate.png'); reference.parent.mkdir(parents=True)
        if kind == 'dangling_symlink':
            reference.symlink_to(root/'missing-reference-target')
        else:
            reference.write_bytes(b'opaque-current' if kind == 'current' else b'opaque-withdrawn-history')
        original = reference.readlink() if reference.is_symlink() else reference.read_bytes()
        before = state_bytes(root)
        response = run_request(client, state, raw)
        assert response.status_code == 409 and 'only_unrecognized: reference;' in response.json()['detail']
        assert state_bytes(root) == before
        assert (reference.readlink() if reference.is_symlink() else reference.read_bytes()) == original


@pytest.mark.parametrize('change', ['source', 'state', 'reference'])
def test_classical_commit_rechecks_exact_source_state_and_reference(app, monkeypatch, change):
    application, root = app; forbid_models(application, monkeypatch)
    original = server.process_image
    def intervening(*args, **kwargs):
        result = original(*args, **kwargs)
        if change == 'source':
            (root/'inputs/demo/plate.png').write_bytes(b'replaced externally')
        elif change == 'state':
            current = json.loads(state_bytes(root)); current['notes'] = 'concurrent note'
            replace_synthetic_state(root, current)
        else:
            ref = server._reference_path(root, 'demo', 'plate.png'); ref.parent.mkdir(parents=True)
            ref.write_bytes(b'new synthetic history')
        return result
    monkeypatch.setattr(server, 'process_image', intervening)
    with TestClient(application) as client:
        raw = upload(client); state = initialized(client); before = state_bytes(root)
        response = run_request(client, state, raw)
        assert response.status_code == 409, response.text
        after = json.loads(state_bytes(root))
        if change == 'state':
            assert after == {**state, 'notes': 'concurrent note'}
        else:
            assert state_bytes(root) == before
        assert after['counted'] is False


def test_classical_default_works_without_models_and_repeat_preserves_result(app, monkeypatch):
    application, root = app; forbid_models(application, monkeypatch)
    for provider in (application.state.model_preview_manager.sam,
                     application.state.model_preview_manager.fusion,
                     application.state.model_preview_manager.fusion_v2):
        monkeypatch.setattr(provider, 'capability', lambda: {'available': False})
    with TestClient(application) as client:
        raw = upload(client, view='unknown'); state = initialized(client)
        assert client.post(BASE+'/viewed', json={'source_sha256': sha(raw)}).status_code == 200
        cfg = client.get('/api/config').json()
        response = run_request(client, state, raw, engine=cfg['default_count_engine'])
        assert response.status_code == 200, response.text
        applied = response.json(); saved = state_bytes(root)
        assert applied['counted'] is True and applied['reviewed'] is False
        assert applied['count_engine'] == server._COMPONENT_ENGINE and applied['count_model'] is None
        assert applied['count_params']['min_value'] == server._INTERNAL_DEFAULT_PARAMS['min_value']
        assert run_request(client, applied, raw).status_code == 409
        assert state_bytes(root) == saved
        assert not server._reference_path(root, 'demo', 'plate.png').exists()


def test_wrong_source_or_revision_rejected_before_processing(app, monkeypatch):
    application, root = app
    monkeypatch.setattr(server, 'process_image', lambda *a, **k: pytest.fail('Stale request must not run'))
    with TestClient(application) as client:
        raw = upload(client); state = initialized(client); before = state_bytes(root)
        assert run_request(client, state, raw, expected_revision=99).status_code == 409
        assert run_request(client, state, raw, expected_image_sha256='a'*64).status_code == 409
        assert state_bytes(root) == before


def test_classical_exception_does_not_commit_partial_staging_output(app, monkeypatch):
    application, root = app; original = server.process_image
    def fail_after_staging(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError('synthetic disk failure before commit')
    monkeypatch.setattr(server, 'process_image', fail_after_staging)
    with TestClient(application) as client:
        raw = upload(client); state = initialized(client); before = state_bytes(root)
        assert run_request(client, state, raw).status_code == 409
        assert state_bytes(root) == before


def test_explicit_false_zero_state_allowed_and_revision_required(app):
    application, root = app
    with TestClient(application) as client:
        raw = upload(client); state = initialized(client)
        state['count_engine'] = 'baseline'; replace_synthetic_state(root, state)
        assert client.post(BASE+'/run', params={'engine':server._COMPONENT_ENGINE,'only_unrecognized':True}).status_code == 422
        assert run_request(client, state, raw).status_code == 200
