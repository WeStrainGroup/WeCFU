"""Synthetic route and source-view checks; no real photos or model inference."""
import copy
import json

import pytest
from fastapi.testclient import TestClient

import wecfu.server.app as server
from wecfu.server import model_preview, sam_runtime, source_views
from test_public_fusion_contract import (
    BASE, app, initialized, install_fake_predict, picture, sha, upload,
)


def sam_request(state, raw):
    return {"engine": sam_runtime.ENGINE, "expected_revision": state["revision"],
            "expected_image_sha256": sha(raw), "model_params": {}}


def apply_request(candidate, state, raw):
    return {"candidate_id": candidate["candidate_id"], "expected_revision": state["revision"],
            "expected_image_sha256": sha(raw), "replace_all": True, "request_id": "synthetic-sam"}


def install_sam(application, monkeypatch, callback=None):
    calls = []
    manager = application.state.model_preview_manager
    def predict(raw, plate, digest):
        assert digest == sha(raw)
        calls.append({"sha256": digest, "plate": server.asdict(plate)})
        if callback:
            callback()
        return [{"id": 1, "cx": 60., "cy": 50., "r": 8., "score": .9,
                 "accepted": True, "source": "cv"}], 1
    monkeypatch.setattr(manager, "predict_sam", predict)
    monkeypatch.setattr(manager, "predict_fusion", lambda *a, **k: pytest.fail("SAM must not call Fusion"))
    monkeypatch.setattr(server, "process_image", lambda *a, **k: pytest.fail("SAM must not fall back to traditional"))
    return calls


def saved_bytes(root):
    return server._det_path(root, "demo", "plate.png").read_bytes()


@pytest.mark.parametrize("available", [False, True])
def test_policy_declares_sam_default_without_availability_fallback(app, monkeypatch, available):
    application, _ = app
    manager = application.state.model_preview_manager
    for provider in (manager.sam, manager.fusion, manager.fusion_v2):
        monkeypatch.setattr(provider, "capability", lambda: {"available": False, "default_model": True})
    monkeypatch.setattr(manager.sam, "capability", lambda: {"available": available})
    with TestClient(application) as client:
        config = client.get("/api/config").json()
    assert config["default_model"] == sam_runtime.ENGINE
    assert config["default_count_engine"] == server._COMPONENT_ENGINE  # Explicit classical/custom route.
    assert config["refinement_model"] == sam_runtime.ENGINE
    assert config["recognition_policy_version"] == "sam-default-explicit-classical-v1"
    assert config["recognition_policy"] == {
        "default_engine": sam_runtime.ENGINE,
        "default_stages": ["classical_seed_preparation", "sam_segmentation", "fixed_postprocessing"],
        "batch_scope": "unrecognized_only", "refinement_engine": sam_runtime.ENGINE,
        "refinement_scope": "current_image_explicit", "automatic_refinement": False,
        "automatic_fallback": False,
    }
    assert config["default_model_fallback"] is False
    assert config["models"]["sam2"]["default_model"] is True
    assert config["models"]["sam2"]["available"] is available
    assert config["import_view_contract"]["default"] == "unknown"
    assert config["import_view_contract"]["requires_user_declaration"] is False
    assert config["models"]["fusion_v2"]["default_model"] is False


@pytest.mark.parametrize("view", ["main", "blank", "back", "unknown"])
def test_sam_supported_view_preview_and_adoption_preserve_provenance(app, monkeypatch, view):
    application, root = app
    calls = install_sam(application, monkeypatch)
    with TestClient(application) as client:
        raw = upload(client, view=view); state = initialized(client); before = saved_bytes(root)
        response = client.post(BASE + "/model-preview", json=sam_request(state, raw))
        assert response.status_code == 200, response.text
        candidate = response.json()
        assert candidate["source_view"] == view and candidate["engine"] == sam_runtime.ENGINE
        assert saved_bytes(root) == before  # Preview is not adoption or human review.
        response = client.post(BASE + "/model-preview/apply", json=apply_request(candidate, state, raw))
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["count_engine"] == sam_runtime.ENGINE
        assert result["count_model"]["model_sha256"] == sam_runtime.MODEL_SHA256
        assert result["count_model"]["recipe_id"] == sam_runtime.RECIPE_ID
        assert result["reviewed"] is False and result["counted"] is True
        assert result["detections"] == candidate["detections"]
        assert len(calls) == 1
        assert not server._reference_path(root, "demo", "plate.png").exists()


@pytest.mark.parametrize("view", ["unknown", "back", "missing", "stale_sha"])
def test_sam_missing_or_stale_view_metadata_uses_unknown_without_rewriting(app, monkeypatch, view):
    application, root = app
    calls = install_sam(application, monkeypatch)
    with TestClient(application) as client:
        raw = upload(client, view=view if view in ("unknown", "back") else "main")
        sidecar = root / "ui-metadata/source-views/demo/plate.png.json"
        if view == "missing":
            sidecar.unlink()
        elif view == "stale_sha":
            record = json.loads(sidecar.read_bytes()); record["source_sha256"] = "0" * 64
            sidecar.write_text(json.dumps(record))
        state = initialized(client); before = saved_bytes(root)
        response = client.post(BASE + "/model-preview", json=sam_request(state, raw))
        assert response.status_code == 200, response.text
        assert response.json()["source_view"] == (view if view in ("unknown", "back") else "unknown")
        assert len(calls) == 1 and saved_bytes(root) == before
        if view == "missing":
            assert not sidecar.exists()
        elif view == "stale_sha":
            assert json.loads(sidecar.read_bytes())["source_sha256"] == "0" * 64


@pytest.mark.parametrize("view", ["blank", "back"])
def test_sam_source_view_change_during_inference_prevents_candidate(app, monkeypatch, view):
    application, root = app
    image = root / "inputs/demo/plate.png"
    calls = install_sam(application, monkeypatch, lambda: source_views.declare(root, "demo", "plate.png", image, view))
    with TestClient(application) as client:
        raw = upload(client); state = initialized(client); before = saved_bytes(root)
        response = client.post(BASE + "/model-preview", json=sam_request(state, raw))
        assert response.status_code == 409, response.text
        assert len(calls) == 1 and saved_bytes(root) == before
        assert not application.state.model_preview_manager._candidates


@pytest.mark.parametrize("view", ["blank", "back"])
def test_sam_source_view_change_before_adoption_preserves_saved_state(app, monkeypatch, view):
    application, root = app; install_sam(application, monkeypatch)
    with TestClient(application) as client:
        raw = upload(client); state = initialized(client)
        response = client.post(BASE + "/model-preview", json=sam_request(state, raw))
        assert response.status_code == 200, response.text
        candidate = response.json(); before = saved_bytes(root)
        assert client.post(BASE + "/source_view", json={"source_sha256": sha(raw), "view": view}).status_code == 200
        response = client.post(BASE + "/model-preview/apply", json=apply_request(candidate, state, raw))
        assert response.status_code == 409, response.text
        assert saved_bytes(root) == before
        assert not (root / "runs/demo/model_preview_recovery").exists()


def test_sam_manual_boundary_allowed_but_explicit_fusion_still_rejects_it(app, monkeypatch):
    application, root = app; calls = install_sam(application, monkeypatch)
    with TestClient(application) as client:
        raw = upload(client); state = initialized(client)
        state["plate_manual"] = True; state["plate"]["r"] = 35.
        server._det_path(root, "demo", "plate.png").write_text(json.dumps(state))
        response = client.post(BASE + "/model-preview", json=sam_request(state, raw))
        assert response.status_code == 200, response.text
        assert calls[0]["plate"] == state["plate"]
        candidate = response.json()
        response = client.post(BASE + "/model-preview/apply", json=apply_request(candidate, state, raw))
        assert response.status_code == 200, response.text
        applied = response.json()
        assert applied["plate_manual"] is True and applied["plate"] == state["plate"]
        before = saved_bytes(root)
        request = {**sam_request(applied, raw), "engine": server.fusion_runtime_v2.ENGINE}
        response = client.post(BASE + "/model-preview", json=request)
        assert response.status_code == 409, response.text
        assert saved_bytes(root) == before and len(calls) == 1


def test_sam_failure_does_not_invoke_fusion_or_traditional_or_write_zero(app, monkeypatch):
    application, root = app; install_sam(application, monkeypatch)
    def unavailable(*args, **kwargs):
        raise model_preview.PreviewError(503, "Synthetic SAM failure; no fallback")
    monkeypatch.setattr(application.state.model_preview_manager, "predict_sam", unavailable)
    with TestClient(application) as client:
        raw = upload(client); state = initialized(client); before = saved_bytes(root)
        response = client.post(BASE + "/model-preview", json=sam_request(state, raw))
        assert response.status_code == 503 and "no fallback" in response.json()["detail"]
        assert saved_bytes(root) == before and not application.state.model_preview_manager._candidates


def test_sam_batch_intent_keeps_existing_human_or_machine_work(app, monkeypatch):
    application, root = app; calls = install_sam(application, monkeypatch)
    with TestClient(application) as client:
        raw = upload(client); state = initialized(client)
        for changes in ({"counted": True}, {"notes": "preserve"}, {"reviewed": True}):
            changed = {**copy.deepcopy(state), **changes}
            server._det_path(root, "demo", "plate.png").write_text(json.dumps(changed)); before = saved_bytes(root)
            response = client.post(BASE + "/model-preview", json={**sam_request(changed, raw), "only_unrecognized": True})
            assert response.status_code == 409, response.text
            assert saved_bytes(root) == before
        assert calls == []


@pytest.mark.parametrize("engine", [server.fusion_runtime_v2.ENGINE, server.fusion_runtime.ENGINE])
def test_stale_single_fusion_request_rejected_before_runtime_or_workspace(app, monkeypatch, engine):
    application, root = app
    manager = application.state.model_preview_manager
    for method in ("predict_sam", "predict_fusion", "predict"):
        monkeypatch.setattr(manager, method, lambda *a, **k: pytest.fail("No model should run"))
    with TestClient(application) as client:
        response = client.post(BASE + "/model-preview", json={"engine": engine, "expected_revision": 0,
            "expected_image_sha256": "a" * 64, "model_params": {}})
        assert response.status_code == 409 and "without DINO" in response.json()["detail"]
        assert not root.exists()


@pytest.mark.parametrize("engine", [server.fusion_runtime_v2.ENGINE,
                                   server.fusion_runtime.ENGINE, model_preview.ENGINE])
def test_stale_model_batch_client_rejected_before_inference_or_writes(app, monkeypatch, engine):
    application, root = app
    manager = application.state.model_preview_manager
    def forbidden(*args, **kwargs):
        pytest.fail("Old batch request must not invoke any model")
    for method in ("predict_sam", "predict_fusion", "predict"):
        monkeypatch.setattr(manager, method, forbidden)
    with TestClient(application) as client:
        raw = upload(client); state = initialized(client)
        before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
        request = {**sam_request(state, raw), "engine": engine, "only_unrecognized": True}
        if engine == model_preview.ENGINE:
            request["model_params"] = {"plate_inset": .95}
        response = client.post(BASE + "/model-preview", json=request)
        assert response.status_code == 409 and "only local SAM" in response.json()["detail"]
        assert manager._candidates == {}
        assert {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()} == before


def test_single_sam_preview_cannot_be_adopted_with_batch_intent(app, monkeypatch):
    application, root = app; install_sam(application, monkeypatch)
    with TestClient(application) as client:
        raw = upload(client); state = initialized(client)
        response = client.post(BASE + "/model-preview", json=sam_request(state, raw))
        assert response.status_code == 200, response.text
        candidate = response.json(); before = saved_bytes(root)
        response = client.post(BASE + "/model-preview/apply", json={**apply_request(candidate, state, raw), "only_unrecognized": True})
        assert response.status_code == 409 and "Reload the page" in response.json()["detail"]
        assert saved_bytes(root) == before
        assert not (root / "runs/demo/model_preview_recovery").exists()
        response = client.post(BASE + "/model-preview/apply", json=apply_request(candidate, state, raw))
        assert response.status_code == 200, response.text


@pytest.mark.parametrize("legacy_engine", [sam_runtime.ENGINE, server.fusion_runtime_v2.ENGINE])
def test_prior_successful_model_batch_receipt_remains_read_only_idempotent(app, monkeypatch, legacy_engine):
    from test_public_fusion_contract import fake_provenance
    application, root = app; install_sam(application, monkeypatch)
    with TestClient(application) as client:
        raw = upload(client); state = initialized(client)
        candidate = client.post(BASE + "/model-preview", json=sam_request(state, raw)).json()
        body = apply_request(candidate, state, raw)
        applied = client.post(BASE + "/model-preview/apply", json=body).json()
        old_body = {**body, "only_unrecognized": True}
        applied["_model_preview_apply"]["request"] = old_body
        if legacy_engine == server.fusion_runtime_v2.ENGINE:
            applied["count_engine"] = legacy_engine
            applied["count_model"] = fake_provenance(raw, state["plate"], "main")
            applied["diagnostics"]["algorithm"] = legacy_engine
        server._det_path(root, "demo", "plate.png").write_text(json.dumps(applied))
        before = saved_bytes(root)
        monkeypatch.setattr(application.state.model_preview_manager, "candidate",
                            lambda *a: pytest.fail("Successful receipt replay must not load a candidate"))
        for provider in (application.state.model_preview_manager.sam,
                         application.state.model_preview_manager.fusion,
                         application.state.model_preview_manager.fusion_v2):
            provider.enabled = False
        response = client.post(BASE + "/model-preview/apply", json=old_body)
        assert response.status_code == 200 and response.json() == applied
        assert saved_bytes(root) == before


@pytest.mark.parametrize('zero', [False, True])
def test_sam_default_batch_preview_apply_and_repeat_preserve_machine_status(app, monkeypatch, zero):
    application, root = app
    calls = install_sam(application, monkeypatch)
    if zero:
        monkeypatch.setattr(application.state.model_preview_manager, 'predict_sam',
                            lambda *a: (calls.append('zero') or [], 0))
    with TestClient(application) as client:
        raw = upload(client, view='unknown'); state = initialized(client); before = saved_bytes(root)
        request = {**sam_request(state, raw), 'only_unrecognized': True}
        response = client.post(BASE+'/model-preview', json=request)
        assert response.status_code == 200, response.text
        candidate = response.json()
        assert candidate['only_unrecognized'] is True and saved_bytes(root) == before
        body = apply_request(candidate, state, raw)
        assert client.post(BASE+'/model-preview/apply', json=body).status_code == 409
        assert saved_bytes(root) == before
        body['only_unrecognized'] = True
        applied = client.post(BASE+'/model-preview/apply', json=body)
        assert applied.status_code == 200, applied.text
        result = applied.json(); after = saved_bytes(root)
        assert result['count_engine'] == sam_runtime.ENGINE
        assert result['reviewed'] is False and result['counted'] is True
        assert result['machine_count_initial'] == (0 if zero else 1)
        assert all(d['source'] == 'cv' for d in result['detections'])
        assert not server._reference_path(root, 'demo', 'plate.png').exists()
        assert client.post(BASE+'/model-preview/apply', json=body).json() == result
        assert saved_bytes(root) == after
        denied = client.post(BASE+'/model-preview', json={**sam_request(result, raw), 'only_unrecognized': True})
        assert denied.status_code == 409 and 'already_counted' in denied.json()['detail']
        assert len(calls) == 1 and saved_bytes(root) == after


from test_batch_model_protection import PROTECTIONS


@pytest.mark.parametrize('reason,changes', PROTECTIONS)
@pytest.mark.parametrize('phase', ['before_preview', 'before_apply'])
def test_sam_default_batch_protects_existing_work_at_both_boundaries(app, monkeypatch, reason, changes, phase):
    application, root = app; calls = install_sam(application, monkeypatch)
    with TestClient(application) as client:
        raw = upload(client); state = initialized(client)
        if phase == 'before_apply':
            preview = client.post(BASE+'/model-preview', json={**sam_request(state, raw), 'only_unrecognized': True})
            assert preview.status_code == 200
            candidate = preview.json()
        protected = {**copy.deepcopy(state), **changes}
        server._det_path(root, 'demo', 'plate.png').write_text(json.dumps(protected)); before = saved_bytes(root)
        if phase == 'before_preview':
            response = client.post(BASE+'/model-preview', json={**sam_request(protected, raw), 'only_unrecognized': True})
        else:
            response = client.post(BASE+'/model-preview/apply', json={**apply_request(candidate, state, raw), 'only_unrecognized': True})
        assert response.status_code == 409, response.text
        assert f'only_unrecognized: {reason};' in response.json()['detail']
        assert saved_bytes(root) == before and len(calls) == (phase == 'before_apply')
        assert not (root/'runs/demo/model_preview_recovery').exists()


@pytest.mark.parametrize('phase', ['before_preview', 'during_inference', 'before_apply'])
@pytest.mark.parametrize('kind', ['history', 'dangling_symlink'])
def test_sam_default_batch_protects_any_reference_without_reading_it(app, monkeypatch, phase, kind):
    application, root = app
    reference = server._reference_path(root, 'demo', 'plate.png')
    def create_reference():
        reference.parent.mkdir(parents=True, exist_ok=True)
        if kind == 'dangling_symlink':
            reference.symlink_to(root/'absent-reference-target')
        else:
            reference.write_bytes(b'opaque synthetic withdrawn history; never parsed')
    calls = install_sam(application, monkeypatch, create_reference if phase == 'during_inference' else None)
    with TestClient(application) as client:
        raw = upload(client); state = initialized(client); before = saved_bytes(root)
        if phase == 'before_preview': create_reference()
        response = client.post(BASE+'/model-preview', json={**sam_request(state, raw), 'only_unrecognized': True})
        if phase == 'before_apply':
            assert response.status_code == 200
            create_reference()
            response = client.post(BASE+'/model-preview/apply', json={**apply_request(response.json(), state, raw), 'only_unrecognized': True})
        assert response.status_code == 409 and 'only_unrecognized: reference;' in response.json()['detail']
        assert saved_bytes(root) == before and len(calls) == (phase != 'before_preview')
        assert reference.is_symlink() if kind == 'dangling_symlink' else reference.read_bytes().startswith(b'opaque')
        assert not (root/'runs/demo/model_preview_recovery').exists()


@pytest.mark.parametrize('change', ['source', 'state'])
def test_sam_default_batch_rejects_changes_during_inference(app, monkeypatch, change):
    application, root = app
    def intervene():
        if change == 'source':
            (root/'inputs/demo/plate.png').write_bytes(picture(151))
        else:
            current = json.loads(saved_bytes(root)); current['notes'] = 'concurrent synthetic note'
            server._det_path(root, 'demo', 'plate.png').write_text(json.dumps(current))
    calls = install_sam(application, monkeypatch, intervene)
    with TestClient(application) as client:
        raw = upload(client); state = initialized(client); before = saved_bytes(root)
        response = client.post(BASE+'/model-preview', json={**sam_request(state, raw), 'only_unrecognized': True})
        assert response.status_code == 409 and len(calls) == 1
        assert not application.state.model_preview_manager._candidates
        assert json.loads(saved_bytes(root)) == ({**state, 'notes': 'concurrent synthetic note'} if change == 'state' else json.loads(before))


def test_unavailable_default_sam_never_runs_classical_or_fusion(app, monkeypatch):
    application, root = app; install_sam(application, monkeypatch)
    manager = application.state.model_preview_manager
    manager.sam.enabled = False
    monkeypatch.setattr(manager, 'predict_sam', lambda *a: pytest.fail('Unavailable SAM must not start'))
    with TestClient(application) as client:
        raw = upload(client); state = initialized(client); before = saved_bytes(root)
        cfg = client.get('/api/config').json()
        assert cfg['default_model'] == sam_runtime.ENGINE and cfg['models']['sam2']['available'] is False
        response = client.post(BASE+'/model-preview', json={**sam_request(state, raw), 'only_unrecognized': True})
        assert response.status_code == 503 and 'no fallback' in response.json()['detail']
        assert saved_bytes(root) == before and not manager._candidates
