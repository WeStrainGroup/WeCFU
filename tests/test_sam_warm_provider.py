"""Provider transport integration with a fake protocol worker and synthetic bytes."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sys

import pytest

from wecfu.server import sam_runtime as sam, sam_warm_pool as warm


FAKE = r'''
import json, sys
from pathlib import Path
for line in sys.stdin:
    command=json.loads(line); folder=Path(command['folder'])
    if command['stage']=='finish':
        request=json.loads((folder/'request.json').read_bytes())
        request.update(status='ok',detections=[],raw_count=0)
        (folder/'result.json').write_text(json.dumps(request))
    print(json.dumps({'id':command['id'],'ok':True}),flush=True)
'''


@dataclass
class Plate:
    cx: float = 20.
    cy: float = 20.
    r: float = 15.


@pytest.fixture
def provider(tmp_path, monkeypatch):
    worker=tmp_path/'worker.py';worker.write_text(FAKE)
    checkpoint=tmp_path/'model';checkpoint.write_bytes(b'synthetic-not-model')
    pool=warm.WarmSamPool();monkeypatch.setattr(warm,'POOL',pool)
    for name,value in [('CHECKPOINT',checkpoint),('WORKER',worker),
                       ('SAM_PYTHON',Path(sys.executable)),('CV_PYTHON',Path(sys.executable))]:
        monkeypatch.setattr(sam,name,value)
    instance=sam.LocalSamProvider()
    checks=[]
    def verified():checks.append(1);return sam.fingerprint(checkpoint)
    monkeypatch.setattr(instance,'require_available',verified)
    monkeypatch.setattr(sam,'sampled_rss',lambda pid:100)
    monkeypatch.setattr(sam.runtime_diagnostics,'preserve_failure',lambda *a,**k:None)
    yield instance,pool,worker,checks
    pool.close()


def predict(provider):
    payload=b'synthetic image bytes, never decoded'
    return provider.predict(payload,Plate(),hashlib.sha256(payload).hexdigest())


@pytest.mark.parametrize('setting', [None, '1'])
def test_default_and_explicit_enable_reuse_workers_but_not_predictions(provider,monkeypatch,setting):
    instance,pool,_,checks=provider
    if setting is None:monkeypatch.delenv('WECFU_SAM_WARM_WORKER',raising=False)
    else:monkeypatch.setenv('WECFU_SAM_WARM_WORKER',setting)
    assert predict(instance)==([],0)
    first=dict(instance.last_timings);pids={role:c['process'].pid for role,c in pool.children.items()}
    assert predict(instance)==([],0)
    assert first['worker_reused'] is False and instance.last_timings['worker_reused'] is True
    assert {role:c['process'].pid for role,c in pool.children.items()}==pids
    assert pool.children['cv']['commands']==4 and pool.children['infer']['commands']==2
    assert len(checks)==4 # Verified before and after every request, not per worker only.
    assert instance.last_timings['status']=='ok'
    assert all(instance.last_timings[key]>=0 for key in ['before_seconds','queue_seconds',
        'prepare_seconds','infer_seconds','finish_seconds','total_seconds'])


def test_explicit_zero_uses_unchanged_cold_cli(provider,monkeypatch):
    instance,pool,_,checks=provider
    monkeypatch.setenv('WECFU_SAM_WARM_WORKER','0')
    commands=[]
    def stage(command,folder,deadline,env):
        commands.append(command)
        if command[-1]=='finish':
            result=json.loads((folder/'request.json').read_bytes())
            result.update(status='ok',detections=[],raw_count=0)
            (folder/'result.json').write_text(json.dumps(result))
        return 10
    monkeypatch.setattr(sam,'run_stage',stage)
    assert predict(instance)==([],0)
    assert [c[-1] for c in commands]==['prepare','infer','finish']
    assert all('--serve' not in command for command in commands)
    assert pool.children=={} and len(checks)==1
    assert instance.last_timings['mode']=='cold'


def test_changed_worker_code_retires_pair_before_loading_new_code(provider,monkeypatch):
    instance,pool,worker,_=provider;monkeypatch.setenv('WECFU_SAM_WARM_WORKER','1')
    predict(instance);old=[c['process'] for c in pool.children.values()]
    worker.write_text(FAKE+'\n# synthetic revision\n')
    predict(instance)
    assert instance.last_timings['worker_reused'] is False
    assert all(process.poll() is not None for process in old)


@pytest.mark.parametrize('replacement',["request.pop('raw_count')", "request['raw_count']=True", "request['raw_count']=-1", "request['image_sha256']='bad'"])
def test_invalid_worker_result_retires_pair_inside_serialized_request(provider,monkeypatch,replacement):
    instance,pool,worker,_=provider;monkeypatch.setenv('WECFU_SAM_WARM_WORKER','1')
    worker.write_text(FAKE.replace("(folder/'result.json').write_text(json.dumps(request))",replacement+"\n        (folder/'result.json').write_text(json.dumps(request))"))
    with pytest.raises(sam.RuntimeUnavailable):predict(instance)
    assert pool.children=={} and instance.last_timings['status']=='failed'


def test_source_hash_failure_never_starts_workers(provider,monkeypatch):
    instance,pool,_,checks=provider;monkeypatch.setenv('WECFU_SAM_WARM_WORKER','1')
    with pytest.raises(sam.RuntimeUnavailable,match='source bytes changed'):
        instance.predict(b'changed',Plate(),'0'*64)
    assert pool.children=={} and not checks
