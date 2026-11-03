"""Fixed deployment deadlines, without importing or running any model."""
import hashlib
import time
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from wecfu.server import fusion_runtime_v2 as fusion, fusion_runtime, model_preview
from wecfu.server.fusion_dino import dino_provider
import wecfu.server.app as server
from test_public_fusion_contract import upload,initialized,preview_request,BASE


class StopAtWorker(Exception):pass


@pytest.mark.parametrize('web,expected',[(False,120.),(True,180.)])
def test_provider_mode_has_fixed_budget_without_environment_override(web,expected,monkeypatch):
    monkeypatch.setenv('WECFU_FUSION_TIMEOUT','99999')
    provider=fusion.LocalFusionProvider(web_mode=web)
    assert provider.timeout_seconds==expected
    monkeypatch.setattr(provider,'require_available',lambda:({},{}))
    assert provider.capability()['wall_timeout_seconds']==expected
    assert fusion_runtime.TIMEOUT_SECONDS==120.


@pytest.mark.parametrize('web,outer,expected',[(False,None,220.),(True,None,280.),
                                             (False,150.,150.),(True,150.,150.),
                                             (False,1000.,220.),(True,1000.,280.)])
def test_sam_receives_capped_same_deadline(web,outer,expected,monkeypatch):
    provider=fusion.LocalFusionProvider(web_mode=web)
    monkeypatch.setattr(provider,'require_available',lambda:({},{}))
    monkeypatch.setattr(fusion,'time',SimpleNamespace(monotonic=lambda:100.))
    observed=[]
    def sam(*args,deadline):observed.append(deadline);raise StopAtWorker()
    monkeypatch.setattr(provider.sam,'predict',sam)
    raw=b'synthetic'
    with pytest.raises(StopAtWorker):provider.predict(raw,None,hashlib.sha256(raw).hexdigest(),1,1,'main',deadline=outer)
    assert observed==[expected]


def test_dino_receives_same_shared_deadline_not_a_new_budget(monkeypatch):
    provider=fusion.LocalFusionProvider(web_mode=True)
    monkeypatch.setattr(provider,'require_available',lambda:({},{}))
    monkeypatch.setattr(fusion,'time',SimpleNamespace(monotonic=lambda:100.))
    monkeypatch.setattr(provider.sam,'predict',lambda *a,**kw:([],0))
    monkeypatch.setattr(fusion.runtime_diagnostics,'preserve_failure',lambda *a,**kw:None)
    deadlines=[]
    def dino(*args,deadline):deadlines.append(deadline);raise StopAtWorker()
    monkeypatch.setattr(dino_provider,'predict_file',dino)
    raw=b'synthetic'
    with pytest.raises(StopAtWorker):provider.predict(raw,server.PlateCircle(1,1,1),hashlib.sha256(raw).hexdigest(),2,2,'main',deadline=160.)
    assert deadlines==[160.]


@pytest.mark.parametrize('outer,wall',[(280.,120.),(150.,50.)])
def test_dino_child_keeps_120_seconds_cpu_and_wall_cap(outer,wall,monkeypatch,tmp_path):
    monkeypatch.setattr(dino_provider,'time',SimpleNamespace(monotonic=lambda:100.))
    monkeypatch.setattr(dino_provider,'verify_contract',lambda pin:None)
    source=tmp_path/'source.image';source.write_bytes(b'synthetic')
    monkeypatch.setattr(dino_provider,'validate_request',lambda *args:source)
    observed=[]
    def supervise(command,**limits):observed.append(limits);raise StopAtWorker()
    monkeypatch.setattr(dino_provider.process_monitor,'supervise',supervise)
    with pytest.raises(StopAtWorker):
        dino_provider.predict_file(source,'a'*64,1,1,{'path':'synthetic'},tmp_path/'out','b'*64,deadline=outer)
    assert observed==[dict(rss_bytes=4*1024**3,wall_seconds=wall,cpu_seconds=120,output_bytes=32*1024**2)]


@pytest.mark.parametrize('web,expected',[(False,220.),(True,280.)])
def test_api_rejects_retired_v2_route_before_inference(web,expected,tmp_path,monkeypatch):
    monkeypatch.setattr(server,'detect_plate',lambda pixels:server.PlateCircle(60,50,40))
    app=server.build_app(lambda:tmp_path/'workspace',web_mode=web)
    observed=[]
    def fake(*args,deadline,engine):
        assert engine==fusion.ENGINE;observed.append(deadline)
        raise model_preview.PreviewError(503,'synthetic stop before model')
    monkeypatch.setattr(app.state.model_preview_manager,'predict_fusion',fake)
    with TestClient(app) as client:
        raw=upload(client);state=initialized(client)
        monkeypatch.setattr(server,'time',SimpleNamespace(monotonic=lambda:100.,perf_counter=time.perf_counter))
        response=client.post(BASE+'/model-preview',json={**preview_request(state,raw),'engine':fusion.ENGINE})
        assert response.status_code==409 and 'without DINO' in response.json()['detail']
    assert observed==[]
