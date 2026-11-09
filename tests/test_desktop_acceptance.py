"""Acceptance harness contracts only; the CLI real model run is separately explicit."""
import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import zipfile

import pytest
from PIL import Image

MODULE=Path(__file__).parents[1]/'tools/desktop_acceptance.py'
spec=importlib.util.spec_from_file_location('desktop_acceptance',MODULE)
accept=importlib.util.module_from_spec(spec);spec.loader.exec_module(accept)


def ready(**changes):
    return {'event':'ready','session_id':'a'*32,'version':'synthetic',
            'url':'http://127.0.0.1:43210/?desktop_session='+('a'*32),**changes}


def test_ready_requires_this_session_and_loopback_authority():
    assert accept.validate_ready(ready(),'a'*32,'synthetic')=='http://127.0.0.1:43210'
    for change in ({'event':'error'},{'session_id':'b'*32},{'version':'different'},
        {'url':'https://127.0.0.1:43210/?desktop_session='+('a'*32)},
        {'url':'http://evil.invalid:43210/?desktop_session='+('a'*32)},
        {'url':'http://127.0.0.1:43210/?desktop_session='+('b'*32)}):
        with pytest.raises(RuntimeError):accept.validate_ready(ready(**change),'a'*32,'synthetic')


def test_synthetic_sources_are_png_and_multipart_preserves_exact_bytes(tmp_path):
    files,version=accept.synthetic_images(tmp_path)
    assert len(files)==2 and version
    assert len({f['sha256'] for f in files})==2
    raw,ctype=accept.multipart(files,'demo')
    assert ctype.startswith('multipart/form-data; boundary=')
    for f in files:
        assert raw.count(f['path'].read_bytes())==1
        with Image.open(f['path']) as im:
            assert im.mode=='RGB' and im.size==(512,512)
    assert b'name="view"\r\n\r\nunknown' in raw


def candidate():
    return {'engine':accept.ENGINE,'recipe_id':accept.RECIPE,'model_sha256':accept.MODEL,
        'image_sha256':'c'*64,'raw_count':2,'candidate_count':1,
        'detections':[{'id':1,'cx':20.,'cy':30.,'r':4.,'score':.9,'accepted':True,'source':'cv'}]}


def test_real_candidate_requires_nonempty_model_provenance_and_finite_geometry():
    value=candidate();accept.verify_candidate(value,'c'*64)
    value['model_sha256']='0'*64
    with pytest.raises(RuntimeError,match='provenance'):accept.verify_candidate(value,'c'*64)
    value=candidate();value['detections'][0]['cx']=float('nan')
    with pytest.raises(RuntimeError,match='Nonfinite'):accept.verify_candidate(value,'c'*64)
    value=candidate();value.update(detections=[],candidate_count=0,raw_count=0)
    with pytest.raises(RuntimeError,match='No usable'):accept.verify_candidate(value,'c'*64)


def test_snapshot_body_deepcopies_only_product_state_fields():
    state={'detections':[{'id':1}],'notes':'synthetic','revision':4,'_private_receipt':{'x':1}}
    body=accept.state_body(state,8)
    assert body=={'detections':[{'id':1}],'notes':'synthetic','expected_revision':8}
    body['detections'][0]['id']=2
    assert state['detections'][0]['id']==1


def exports(states, *, dimensions=(507,507)):
    stream=io.StringIO();writer=csv.writer(stream)
    writer.writerow(['filename','total_count','machine_count','n_removed','n_added','notes'])
    for name,state in states.items():
        writer.writerow([name,len(state['detections']),state['machine_count_initial'],0,1,state['notes']])
    csvraw=stream.getvalue().encode();output=io.BytesIO()
    png=io.BytesIO();Image.new('RGB',dimensions).save(png,format='PNG')
    with zipfile.ZipFile(output,'w') as archive:
        archive.writestr('demo.csv',csvraw)
        for name,state in states.items():
            archive.writestr('detections/'+name+'.json',json.dumps(state))
            archive.writestr('overlays/'+name+'.png',png.getvalue())
    return csvraw,output.getvalue()


def test_export_oracle_catches_count_and_saved_state_mismatch():
    states={'one.png':{'detections':[{'source':'cv'},{'source':'manual'}],
                      'machine_count_initial':1,'notes':'synthetic, Unicode 测试',
                      'plate':{'cx':255.36,'cy':257.664,'r':228.9408},
                      'image_size':{'width':512,'height':512}}}
    csvraw,zipraw=exports(states)
    assert accept.verify_exports(csvraw,zipraw,states)['zip_states_exact']
    assert accept.verify_exports(csvraw,zipraw,states)['overlay_dimensions']=={'one.png':[507,507]}
    wrongcsv,wrongzip=exports(states,dimensions=(512,512))
    with pytest.raises(RuntimeError,match='plate bbox'):
        accept.verify_exports(wrongcsv,wrongzip,states)
    with pytest.raises(RuntimeError,match='CSV count'):
        accept.verify_exports(csvraw.replace(b',2,1,',b',3,1,'),zipraw,states)
    states['one.png']['detections'][0]['cx']=10
    with pytest.raises(RuntimeError,match='ZIP state'):
        accept.verify_exports(csvraw,zipraw,states)


def test_overlay_dimensions_clip_to_image_without_resizing():
    assert accept.overlay_dimensions({'plate':{'cx':4.2,'cy':10.9,'r':30.},
        'image_size':{'width':80,'height':100}})==(59,65)


def test_saved_export_continuation_checks_bound_receipt_before_reading_payloads(tmp_path):
    (tmp_path/'result.json').write_text(json.dumps({'status':'failed'}))
    with pytest.raises(RuntimeError,match='receipt SHA'):
        accept.verify_saved_exports(tmp_path,'0'*64)


def test_continuation_never_invokes_model_workflow_and_starts_two_empty_hosts(tmp_path,monkeypatch):
    from types import SimpleNamespace
    bundle=tmp_path/'bundle';bundle.mkdir()
    (bundle/'bundle-manifest.json').write_text('{}');(bundle/'python').touch()
    manifest={'python':'python','app_version':'synthetic','platform':'synthetic','files':{}}
    monkeypatch.setattr(accept,'verify_bundle',lambda root:manifest)
    monkeypatch.setattr(accept,'verify_saved_exports',lambda *a:{'new_model_requests':0})
    monkeypatch.setattr(accept.subprocess,'run',lambda *a,**k:SimpleNamespace(stdout='{}'))
    monkeypatch.setattr(accept,'exercise',lambda *a:pytest.fail('continuation invoked inference workflow'))
    monkeypatch.setattr(accept,'synthetic_images',lambda *a:pytest.fail('continuation generated new inputs'))
    hosts=[]
    class FakeHost:
        def __init__(self,*a):
            self.session='synthetic';self.startup_seconds=0;self.cleanup={}
            self.client=SimpleNamespace(request=self.request,preview_attempts=0,preview_success_responses=0)
            self.requests=[];hosts.append(self)
        def request(self,method,path,**kw):
            self.requests.append((method,path,kw))
            assert method=='GET'
            return {'batches':[]}
        def start(self):return self
        def shutdown(self):self.cleanup={'exit_code':0,'remaining_temp_entries':[]}
        def close(self):pass
    monkeypatch.setattr(accept,'Host',FakeHost)
    output=tmp_path/'new-evidence'
    monkeypatch.setattr(accept.sys,'argv',['accept','--bundle',str(bundle),'--output',str(output),
        '--continue-from',str(tmp_path/'old'),'--prior-receipt-sha256','a'*64])
    assert accept.main()==0
    result=json.loads((output/'result.json').read_text())
    assert result['status']=='passed' and result['real_model_requests']==result['real_model_request_attempts']==0
    assert len(hosts)==2 and all(h.cleanup['exit_code']==0 for h in hosts)


def test_temp_cleanup_only_allows_empty_non_session_torch_import_directory(tmp_path,monkeypatch):
    cache=tmp_path/'torchinductor_synthetic';cache.mkdir()
    assert accept.remaining_session_entries(tmp_path)==([],['torchinductor_synthetic'])
    workspace=tmp_path/'wecfu-desktop-synthetic';workspace.mkdir()
    assert accept.remaining_session_entries(tmp_path)==(['wecfu-desktop-synthetic'],['torchinductor_synthetic'])
    workspace.rmdir()
    (cache/'source.image').write_bytes(b'synthetic')
    assert accept.remaining_session_entries(tmp_path)==(['torchinductor_synthetic'],[])
    (cache/'source.image').unlink();cache.rmdir()
    (tmp_path/'unknown-empty').mkdir()
    assert accept.remaining_session_entries(tmp_path)==(['unknown-empty'],[])
    (tmp_path/'unknown-empty').rmdir();cache.mkdir()
    monkeypatch.setattr(Path,'is_junction',lambda path:path==cache,raising=False)
    assert accept.remaining_session_entries(tmp_path)==(['torchinductor_synthetic'],[])


def test_bundle_byte_verification_rejects_changed_or_escaping_files(tmp_path):
    (tmp_path/'app').mkdir();source=tmp_path/'app/entry.py';source.write_bytes(b'synthetic')
    manifest={'schema_version':1,'files':{'app/entry.py':hashlib.sha256(b'synthetic').hexdigest()}}
    (tmp_path/'bundle-manifest.json').write_text(json.dumps(manifest))
    assert accept.verify_bundle(tmp_path)==manifest
    extra=tmp_path/'unmanifested.py';extra.write_bytes(b'unexpected')
    with pytest.raises(RuntimeError,match='inventory'):accept.verify_bundle(tmp_path)
    extra.unlink()
    source.write_bytes(b'changed')
    with pytest.raises(RuntimeError,match='integrity'):accept.verify_bundle(tmp_path)
    for relative in ('../x','/absolute','a\\b','a//b'):
        with pytest.raises(RuntimeError):accept.bundle_path(tmp_path,relative)


def test_final_cleanup_failure_cannot_leave_success_and_preserves_completed_requests():
    from types import SimpleNamespace
    def failed_close():
        raise RuntimeError('synthetic job cleanup failure')
    host=SimpleNamespace(client=SimpleNamespace(preview_attempts=2,preview_success_responses=1),close=failed_close)
    receipt={'status':'passed','real_model_requests':0}
    accept.close_host(host,receipt)
    assert receipt['status']=='failed' and 'cleanup failure' in receipt['cleanup_error']
    assert receipt['real_model_request_attempts']==2 and receipt['real_model_requests']==1
