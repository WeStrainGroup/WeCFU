"""Synthetic unified-import Web integrations with model-free defaults."""
from fastapi.testclient import TestClient

import wecfu.server.app as server
from wecfu.server.web import SESSION_COOKIE, build_web_app
from test_public_fusion_contract import BASE, initialized, upload
from test_batch_model_protection import run_request, forbid_models


def web_fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(server, 'detect_plate', lambda pixels: server.PlateCircle(60, 50, 40))
    monkeypatch.setattr('wecfu.pipeline.detect_plate', lambda pixels: server.PlateCircle(60, 50, 40))
    sessions = tmp_path/'sessions'
    application = build_web_app(sessions)
    forbid_models(application, monkeypatch)
    return application, sessions


def test_web_builtin_default_and_repeat_protection(tmp_path, monkeypatch):
    application, _ = web_fixture(tmp_path, monkeypatch)
    with TestClient(application, base_url='https://testserver') as client:
        raw = upload(client, view='unknown'); state = initialized(client)
        cfg = client.get('/api/config').json()
        assert cfg['default_count_engine'] == 'baseline' and cfg['default_model'] is None
        assert cfg['refinement_model'] == server.sam_runtime.ENGINE
        response = run_request(client, state, raw, engine=cfg['default_count_engine'])
        assert response.status_code == 200, response.text
        applied = response.json()
        assert applied['count_engine'] == 'baseline' and applied['counted'] is True
        assert run_request(client, applied, raw, engine='baseline').status_code == 409
        assert client.get(BASE+'/detections').json() == applied
        assert run_request(client, state, raw, engine=server._COMPONENT_ENGINE).status_code == 403


def test_web_classical_results_are_session_isolated(tmp_path, monkeypatch):
    application, _ = web_fixture(tmp_path, monkeypatch)
    with TestClient(application, base_url='https://testserver') as one, TestClient(application, base_url='https://testserver') as two:
        raw = upload(one); upload(two)
        a = initialized(one); b = initialized(two)
        assert one.cookies.get(SESSION_COOKIE) != two.cookies.get(SESSION_COOKIE)
        assert run_request(one, a, raw, engine='baseline').status_code == 200
        assert two.get(BASE+'/detections').json() == b


def test_web_human_marks_and_hidden_reference_block_classical_batch(tmp_path, monkeypatch):
    application, sessions = web_fixture(tmp_path, monkeypatch)
    with TestClient(application, base_url='https://testserver') as client:
        raw = upload(client); initialized(client)
        assert client.post(BASE+'/detections', json={'cx':60.,'cy':50.,'r':4.}).status_code == 200
        edited = client.get(BASE+'/detections').json()
        denied = run_request(client, edited, raw, engine='baseline')
        assert denied.status_code == 409 and 'existing_marks' in denied.json()['detail']
        upload(client, name='reference.png'); other='/api/batch/demo/image/reference.png'
        state=client.post(other+'/initialize',json={'mode':'auto'}).json()
        root=sessions/client.cookies.get(SESSION_COOKIE)
        reference=server._reference_path(root,'demo','reference.png');reference.parent.mkdir(parents=True)
        reference.write_bytes(b'opaque synthetic withdrawn reference history')
        before=server._det_path(root,'demo','reference.png').read_bytes()
        denied=run_request(client,state,raw,engine='baseline',base=other)
        assert denied.status_code==409 and 'only_unrecognized: reference;' in denied.json()['detail']
        assert client.get(other+'/reference').status_code==403
        assert server._det_path(root,'demo','reference.png').read_bytes()==before
