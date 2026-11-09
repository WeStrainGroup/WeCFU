"""One bounded offline desktop API acceptance using two generated images.

This exercises the bundled Python/entrypoint, not a browser/WebView. It never
uses photographs or human references, retries inference, or changes recipes.
Run native transport tests alone with --transport-only (no model loading).
"""
from __future__ import annotations
import argparse
from copy import deepcopy
import csv
import hashlib
from http.cookiejar import CookieJar
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import platform
import queue
import signal
import subprocess
import sys
import threading
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit, parse_qs, quote
from urllib.request import Request, build_opener, HTTPCookieProcessor, ProxyHandler
from uuid import uuid4
import zipfile

REPO = Path(__file__).resolve().parents[1]
STARTUP_SECONDS = 120
PREVIEW_SECONDS = 120
RESPONSE_BYTES = 64 * 1024**2
ENGINE = 'sam2_local_v1'
RECIPE = 'sam_cv_seed_area0.05_color160_edge095_v1'
MODEL = '7402e0d864fa82708a20fbd15bc84245c2f26dff0eb43a4b5b93452deb34be69'
STATE_KEYS = ('detections','plate','mode','machine_count_initial','notes','plate_manual',
              'reviewed','params','counted','count_params','count_engine','count_model')


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write('\n')


def sha(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024**2), b''):
            value.update(block)
    return value.hexdigest()


def bundle_path(root, relative):
    require(type(relative) is str and relative and '\\' not in relative, 'Invalid bundle path')
    path = PurePosixPath(relative)
    require(not path.is_absolute() and all(p not in ('.','..','') for p in relative.split('/')),
            'Unsafe bundle relative path')
    target = root.joinpath(*path.parts)
    require(target.resolve().is_relative_to(root.resolve()) and target.is_file(), 'Missing/escaping bundle file')
    return target


def verify_bundle(root):
    manifest = json.loads((root/'bundle-manifest.json').read_text())
    require(manifest['schema_version'] == 1 and manifest['files'], 'Invalid bundle manifest')
    actual={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
    require(actual==set(manifest['files'])|{'bundle-manifest.json'},'Bundle inventory differs from manifest')
    require(not any(p.is_symlink() for p in root.rglob('*')),'Bundle contains a symlink')
    for relative, expected in manifest['files'].items():
        require(sha(bundle_path(root, relative)) == expected, 'Bundle integrity failure: '+relative)
    return manifest


def validate_ready(value, session, version):
    require(value.get('event') == 'ready' and value.get('session_id') == session
            and value.get('version') == version, 'Desktop did not emit the expected ready handshake')
    url = urlsplit(value['url'])
    require(url.scheme == 'http' and url.hostname == '127.0.0.1' and url.port
            and url.path == '/' and not url.fragment and not url.username
            and parse_qs(url.query) == {'desktop_session':[session]}, 'Unsafe desktop ready URL')
    return f'http://127.0.0.1:{url.port}'


def synthetic_images(folder):
    from PIL import Image, ImageDraw, __version__
    files = []
    for index, spots in enumerate((((174,196,13),(328,302,16)),
                                   ((168,308,15),(328,180,12))), 1):
        image = Image.new('RGB',(512,512),(24,24,24))
        draw = ImageDraw.Draw(image)
        draw.ellipse((26,26,486,486),fill=(85,85,85),outline=(170,170,170),width=3)
        for x,y,radius in spots:
            draw.ellipse((x-radius,y-radius,x+radius,y+radius),fill=(245,245,230))
        path = folder/f'synthetic-{index}.png'
        image.save(path)
        files.append({'path':path,'sha256':sha(path),'generated_spots':len(spots)})
    return files, __version__


def multipart(files, batch):
    boundary = 'wecfu-synthetic-'+uuid4().hex
    parts = []
    for name,value in [('batch',batch),('view','unknown')]:
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    for file in files:
        path = file['path']
        parts += [f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="{path.name}"\r\nContent-Type: image/png\r\n\r\n'.encode(),path.read_bytes(),b'\r\n']
    parts.append(f'--{boundary}--\r\n'.encode())
    return b''.join(parts), 'multipart/form-data; boundary='+boundary


def remaining_session_entries(temp_root):
    """Distinguish the empty directory created by Torch import from user data."""
    blocking, empty_runtime_directories = [], []
    for path in sorted(temp_root.iterdir()):
        if (path.name.startswith('torchinductor_') and not path.is_symlink()
                and not getattr(path, 'is_junction', lambda: False)()
                and path.is_dir() and not any(path.iterdir())):
            empty_runtime_directories.append(path.name)
        else:
            blocking.append(path.name)
    return blocking, empty_runtime_directories


class Client:
    def __init__(self, origin, folder):
        self.origin, self.folder = origin, folder
        self.opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(CookieJar()))
        self.records = []
        self.preview_attempts = 0
        self.preview_success_responses = 0

    def request(self, method, path, *, body=None, raw=None, headers=None, status=200, timeout=30):
        hdr = {'Origin': self.origin, **(headers or {})}
        if body is not None:
            raw=json.dumps(body,allow_nan=False).encode();hdr['Content-Type']='application/json'
        before = time.monotonic()
        if method == 'POST' and path.endswith('/model-preview') and status == 200:
            self.preview_attempts += 1
        request = Request(self.origin+path,data=raw,method=method,headers=hdr)
        try:
            response = self.opener.open(request,timeout=timeout)
        except HTTPError as exc:
            response = exc
        with response:
            payload=response.read(RESPONSE_BYTES+1)
            require(len(payload)<=RESPONSE_BYTES,'HTTP response exceeds acceptance budget')
            code=response.status
            response_headers={k.lower():v for k,v in response.headers.items()}
        number=len(self.records)
        target=self.folder/f'http-{number:03d}.body'
        target.write_bytes(payload)
        self.records.append({'method':method,'path':path,'status':code,'seconds':time.monotonic()-before,
            'body_file':target.name,'sha256':sha(target),'bytes':len(payload),'headers':response_headers})
        save(self.folder/f'http-{number:03d}.json',self.records[-1])
        if method == 'POST' and path.endswith('/model-preview') and status == 200 and code == 200:
            self.preview_success_responses += 1
        require(code==status,f'{method} {path} returned {code}, expected {status}; body retained at {target.name}')
        if response_headers.get('content-type','').startswith('application/json'):
            return json.loads(payload)
        return payload


class Host:
    def __init__(self, bundle, manifest, folder, temp_root):
        self.bundle,self.manifest,self.folder,self.temp_root=bundle,manifest,folder,temp_root
        self.session=uuid4().hex;self.process=None;self.thread=None
        self.stderr=None;self.ready_queue=queue.Queue(maxsize=1)
        self.cleanup={}

    def start(self):
        self.folder.mkdir()
        python=bundle_path(self.bundle,self.manifest['python'])
        entry=bundle_path(self.bundle,self.manifest['entrypoint'])
        env={k:v for k,v in os.environ.items() if not k.startswith(('PYTHON','WECFU_'))}
        env.update(PYTHONNOUSERSITE='1',PYTHONDONTWRITEBYTECODE='1',
                   TMPDIR=str(self.temp_root),TMP=str(self.temp_root),TEMP=str(self.temp_root))
        command=[str(python),'-B',str(entry),'--resource-root',str(self.bundle),'--session-id',self.session]
        self.stderr=(self.folder/'stderr.log').open('xb')
        if sys.platform=='win32':
            # Same bundled entrypoint, with a one-byte Job ownership gate. No
            # application code executes before assignment; stdin remains intact.
            sys.path.insert(0,str(REPO))
            from wecfu.platform_runtime import spawn_owned
            self.process=spawn_owned(command,cwd=self.bundle,env=env,stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,stderr=self.stderr,bufsize=0)
        else:
            command.insert(1,'-I')
            self.process=subprocess.Popen(command,cwd=self.bundle,env=env,stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,stderr=self.stderr,bufsize=0,start_new_session=True)
        def read_ready():
            with (self.folder/'stdout.log').open('xb') as log:
                line=self.process.stdout.readline(4097)
                log.write(line);log.flush()
                self.ready_queue.put(line)
                # All further stdout is diagnostic protocol, preserved on disk.
                for line in iter(lambda:self.process.stdout.read(4096),b''):
                    log.write(line);log.flush()
        self.thread=threading.Thread(target=read_ready,daemon=True)
        self.thread.start()
        before=time.monotonic()
        try:
            raw=self.ready_queue.get(timeout=STARTUP_SECONDS)
        except queue.Empty as exc:
            raise RuntimeError('Desktop startup exceeded 120 seconds') from exc
        require(len(raw)<=4096 and raw.endswith(b'\n'),'Invalid desktop ready framing')
        ready=json.loads(raw)
        self.origin=validate_ready(ready,self.session,self.manifest['app_version'])
        self.startup_seconds=time.monotonic()-before
        self.client=Client(self.origin,self.folder)
        return self

    def shutdown(self):
        require(self.process is not None,'Host not started')
        before=time.monotonic()
        self.process.stdin.write(json.dumps({'command':'shutdown','session_id':self.session}).encode()+b'\n')
        self.process.stdin.flush()
        code=self.process.wait(timeout=20)
        self.thread.join(3)
        self.stderr.flush()
        remaining, empty_runtime=remaining_session_entries(self.temp_root)
        self.cleanup={'exit_code':code,'seconds':time.monotonic()-before,'remaining_temp_entries':remaining,
                      'empty_non_session_runtime_directories':empty_runtime,
                      'stdout_reader_stopped':not self.thread.is_alive()}
        require(code==0,'Desktop graceful shutdown failed')
        require(not remaining,'Desktop left temporary session data behind')
        require(not self.thread.is_alive(),'Desktop stdout reader did not stop')
        if sys.platform!='win32':
            try:os.killpg(self.process.pid,0)
            except ProcessLookupError:pass
            else:raise RuntimeError('Desktop left a child in its process group')
        else:
            from wecfu import platform_runtime
            _,api,job=platform_runtime._OWNED[self.process.pid]
            require(api.active(job)==0,'Desktop left a live Job child after graceful shutdown')
        self.cleanup['owned_children_gone']=True
        require(b'Traceback' not in (self.folder/'stderr.log').read_bytes(),'Traceback in desktop stderr')

    def close(self):
        if self.process is not None:
            if sys.platform=='win32':
                from wecfu.platform_runtime import stop_owned
                stop_owned(self.process)
            else:
                try:os.killpg(self.process.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                self.process.wait(timeout=5)
            if self.thread:self.thread.join(3)
            for stream in (self.process.stdin,self.process.stdout):
                if stream:stream.close()
        if self.stderr:self.stderr.close()


def state_body(state, revision):
    result={key:deepcopy(state[key]) for key in STATE_KEYS if key in state}
    result['expected_revision']=revision
    return result


def verify_candidate(candidate, digest):
    require(candidate['engine']==ENGINE and candidate['recipe_id']==RECIPE
            and candidate['model_sha256']==MODEL and candidate['image_sha256']==digest,'Model provenance mismatch')
    require(candidate['candidate_count']==len(candidate['detections'])>0 and
            candidate['raw_count']>=candidate['candidate_count'],'No usable real SAM candidate')
    require(len({d['id'] for d in candidate['detections']})==candidate['candidate_count'],'Repeated detection ID')
    for d in candidate['detections']:
        require(d['source']=='cv' and d['accepted'] is True,'Unexpected machine mark source')
        require(all(type(d[k]) in (int,float) and math.isfinite(d[k]) for k in ('cx','cy','r','score')),'Nonfinite geometry')
        require(0<=d['cx']<512 and 0<=d['cy']<512 and d['r']>0 and 0<=d['score']<=1,'Invalid candidate geometry')


def overlay_dimensions(state):
    """Product exports the plate bounding box plus 24 px, without resizing."""
    plate, size = state['plate'], state['image_size']
    x0 = max(0, int(plate['cx'] - plate['r'] - 24))
    y0 = max(0, int(plate['cy'] - plate['r'] - 24))
    x1 = min(size['width'], math.ceil(plate['cx'] + plate['r'] + 24))
    y1 = min(size['height'], math.ceil(plate['cy'] + plate['r'] + 24))
    require(x1 > x0 and y1 > y0, 'Invalid exported plate bounding box')
    return x1 - x0, y1 - y0


def verify_exports(csv_raw, zip_raw, states):
    def check_csv(raw):
        rows=list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
        require(len(rows)==len(states),'CSV image inventory mismatch')
        require({r['filename'] for r in rows}==set(states),'CSV names mismatch')
        for row in rows:
            state=states[row['filename']];marks=state['detections']
            cv=sum(d['source']=='cv' for d in marks);manual=sum(d['source']=='manual' for d in marks)
            expected=[len(marks),state['machine_count_initial'],state['machine_count_initial']-cv,manual]
            require([int(row[k]) for k in ('total_count','machine_count','n_removed','n_added')]==expected,'CSV count mismatch')
            require(row['notes']==state['notes'],'CSV notes mismatch')
    check_csv(csv_raw)
    with zipfile.ZipFile(io.BytesIO(zip_raw)) as archive:
        names=archive.namelist()
        require(len(names)==len(set(names)),'Duplicate ZIP members')
        csv_names=[n for n in names if n.endswith('.csv')]
        require(len(csv_names)==1,'ZIP CSV inventory mismatch')
        check_csv(archive.read(csv_names[0]))
        require({n for n in names if n.startswith('detections/')} == {'detections/'+name+'.json' for name in states},'ZIP detection inventory mismatch')
        require(len(names)==1+2*len(states),'Unexpected ZIP member inventory')
        for name,state in states.items():
            require(json.loads(archive.read('detections/'+name+'.json'))==state,'ZIP state differs from saved API state')
        overlays={n for n in names if n.startswith('overlays/')}
        require(overlays=={'overlays/'+name+'.png' for name in states},'ZIP overlays incomplete')
        from PIL import Image
        for name, state in states.items():
            with Image.open(io.BytesIO(archive.read('overlays/'+name+'.png'))) as image:
                require(image.size==overlay_dimensions(state),'ZIP overlay differs from plate bbox + 24 contract')
                image.verify()
    return {'images':len(states),'csv_exact':True,'zip_states_exact':True,
            'overlay_contract':'plate_bbox_plus24_crop_without_resize',
            'overlay_dimensions':{name:list(overlay_dimensions(state)) for name,state in states.items()}}


def verify_saved_exports(folder, expected_receipt_sha256):
    """Read-only recovery from a harness export assertion, never run a model."""
    require(sha(folder/'result.json') == expected_receipt_sha256, 'Prior receipt SHA mismatch')
    prior=json.loads((folder/'result.json').read_text())
    require(prior['status']=='failed' and prior['explicit_synthetic'] is True
            and prior['error']=='ZIP overlay cropped/resized unexpectedly'
            and prior['real_model_requests']==prior['real_model_request_attempts']==2,
            'Not the known completed-inference export assertion failure')
    actual={p.relative_to(folder).as_posix() for p in folder.rglob('*') if p.is_file()}
    require(actual==set(prior['files'])|{'result.json'},'Prior evidence inventory changed')
    for relative, digest in prior['files'].items():
        require(sha(bundle_path(folder,relative))==digest,'Prior evidence SHA mismatch')
    names=[Path(row['path']).name for row in prior['inputs']]
    require(len(names)==len(set(names))==2,'Prior input inventory mismatch')
    records=[json.loads(p.read_text()) for p in sorted((folder/'launch-001').glob('http-*.json'))]
    states={};exports={};model_receipts=[];source_files={}
    for row in records:
        body=folder/'launch-001'/row['body_file']
        require(sha(body)==row['sha256'],'HTTP body SHA mismatch')
        if row['status']!=200:
            continue
        for name in names:
            base='/api/batch/synthetic-acceptance/image/'+quote(name)
            if ((row['method']=='GET' and row['path']==base+'/detections') or
                    (row['method']=='PUT' and row['path']==base+'/state')):
                states[name]=json.loads(body.read_text());source_files[name]=body.relative_to(folder).as_posix()
            if row['method']=='POST' and row['path']==base+'/model-preview':
                candidate=json.loads(body.read_text())
                digest=next(r['sha256'] for r in prior['inputs'] if Path(r['path']).name==name)
                verify_candidate(candidate,digest)
                model_receipts.append({'name':name,'seconds':row['seconds'],'candidate_count':candidate['candidate_count'],
                                       'recipe':candidate['recipe_id'],'model_sha256':candidate['model_sha256']})
        for kind in ('csv','zip'):
            if row['method']=='GET' and row['path']=='/api/batch/synthetic-acceptance/export.'+kind:
                require(kind not in exports,'Duplicate export response')
                exports[kind]=body.read_bytes()
    require(set(states)==set(names) and set(exports)=={'csv','zip'} and len(model_receipts)==2,
            'Prior API evidence incomplete')
    return {'original_receipt':str(folder/'result.json'),'original_receipt_sha256':expected_receipt_sha256,
            'original_status_preserved':'failed','prior_manifest_sha256':prior['manifest_sha256'],
            'state_authority_api_responses':source_files,'prior_model_responses':model_receipts,
            'exports':verify_exports(exports['csv'],exports['zip'],states),
            'initial_shutdown':'not established: original assertion failure forced host cleanup',
            'new_model_requests':0}


def exercise(host, images, batch):
    client=host.client
    require(client.request('GET','/api/batches',status=403),'Missing unauthorized rejection body')
    client.request('GET','/?desktop_session='+host.session)
    client.request('GET','/api/batches',headers={'Host':'unrelated.invalid'},status=403)
    client.request('GET','/api/batches',headers={'Origin':'https://unrelated.invalid'},status=403)
    client.request('POST','/api/ingest',body={'paths':[]},headers={'Origin':''},status=403)
    require(client.request('GET','/api/batches')['batches']==[],'Desktop did not start empty')
    config=client.request('GET','/api/config',timeout=120)
    require(config['default_model']==ENGINE and config['models']['sam2']['available'] is True,'Ultra not available in actual bundle')
    data,ctype=multipart(images,batch)
    imported=client.request('POST','/api/upload',raw=data,headers={'Content-Type':ctype})
    names=[x['path'].name for x in images]
    require(imported['names']==names and imported['uploaded']==2,'Upload changed image inventory')
    states={};models=[]
    for index,image in enumerate(images):
        base=f'/api/batch/{batch}/image/{quote(image["path"].name)}'
        state=client.request('POST',base+'/initialize',body={'mode':'auto'})
        require(state['counted'] is False and not state['detections'],'Unexpected imported state')
        raw=client.request('GET',base+'/raw?display_context=true')
        require(hashlib.sha256(raw).hexdigest()==image['sha256'],'Displayed source bytes differ')
        require(client.records[-1]['headers'].get('x-wecfu-source-sha256')==image['sha256'],'Display SHA missing')
        body={'engine':ENGINE,'expected_revision':state['revision'],'expected_image_sha256':image['sha256'],
              'model_params':{},'only_unrecognized':bool(index)}
        candidate=client.request('POST',base+'/model-preview',body=body,timeout=PREVIEW_SECONDS)
        verify_candidate(candidate,image['sha256'])
        require(client.records[-1]['seconds']<=PREVIEW_SECONDS,'Preview exceeded 120-second wall budget')
        apply={'candidate_id':candidate['candidate_id'],'expected_revision':state['revision'],
               'expected_image_sha256':image['sha256'],'replace_all':True,'request_id':uuid4().hex,
               'only_unrecognized':bool(index)}
        adopted=client.request('POST',base+'/model-preview/apply',body=apply)
        require(adopted['detections']==candidate['detections'] and adopted['counted'] is True,'Candidate adoption changed detections')
        require(client.request('POST',base+'/model-preview/apply',body=apply)==adopted,'Apply retry not idempotent')
        blocked={**body,'expected_revision':adopted['revision'],'only_unrecognized':True}
        rejection=client.request('POST',base+'/model-preview',body=blocked,status=409)
        require('only_unrecognized:' in str(rejection.get('detail','')),'Repeat was not rejected by the batch-protection gate')
        require(client.request('GET',base+'/detections')==adopted,'Protected second preview mutated state')
        states[image['path'].name]=adopted
        models.append({'name':image['path'].name,'candidate':candidate,'provenance':adopted['count_model'],
                       'mode':'current' if index==0 else 'batch_only_unrecognized'})
    # Exactly the UI's state snapshot operations, never a reference endpoint.
    name=names[0];base=f'/api/batch/{batch}/image/{quote(name)}';before=states[name]
    client.request('POST',base+'/detections',body={'cx':256,'cy':256,'r':7})
    client.request('PUT',base+'/notes',body={'notes':'Synthetic acceptance only; not human reference data.'})
    edited=client.request('GET',base+'/detections')
    require(len(edited['detections'])==len(before['detections'])+1 and edited['detections'][-1]['source']=='manual','Manual edit missing')
    undone=client.request('PUT',base+'/state',body=state_body(before,edited['revision']))
    require(all(undone[k]==before[k] for k in STATE_KEYS if k in before),'Undo failed to restore snapshot')
    redone=client.request('PUT',base+'/state',body=state_body(edited,undone['revision']))
    require(all(redone[k]==edited[k] for k in STATE_KEYS if k in edited),'Redo failed to restore edit')
    states[name]=redone
    csv_raw=client.request('GET',f'/api/batch/{batch}/export.csv')
    zip_raw=client.request('GET',f'/api/batch/{batch}/export.zip')
    export=verify_exports(csv_raw,zip_raw,states)
    save(host.folder/'states.json',states)
    return {'model_requests':2,'config':config,'models':models,'manual_undo_redo':True,
            'host_origin_unauth_rejections':True,'repeat_batch_refused':True,'exports':export}


def close_host(host, receipt):
    """Never leave a passed receipt if final ownership/handle cleanup failed."""
    if host is None:
        return
    if hasattr(host, 'client'):
        receipt['real_model_request_attempts'] = max(receipt.get('real_model_request_attempts', 0), host.client.preview_attempts)
        receipt['real_model_requests'] = max(receipt.get('real_model_requests', 0), host.client.preview_success_responses)
    if getattr(host, 'cleanup', None):
        receipt['last_host_cleanup'] = deepcopy(host.cleanup)
    try:
        host.close()
    except Exception as exc:
        receipt['status'] = 'failed'
        receipt['cleanup_error'] = type(exc).__name__ + ': ' + str(exc)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle',type=Path,default=REPO/'desktop/bundle')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--transport-only',action='store_true')
    parser.add_argument('--continue-from',type=Path,help='Offline export recheck and fresh empty-host lifecycle only; no inference')
    parser.add_argument('--prior-receipt-sha256')
    parsed=parser.parse_args()
    if parsed.continue_from and (parsed.transport_only or not parsed.prior_receipt_sha256):
        parser.error('--continue-from requires --prior-receipt-sha256 and excludes --transport-only')
    args=parsed;out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    receipt={'status':'failed','explicit_synthetic':True,'real_model_requests':0,
        'acceptance_source_sha256':sha(Path(__file__)),
        'real_model_requests_meaning':'Number of non-retried model-preview HTTP 200 responses, not a biological accuracy claim',
        'os':sys.platform,'architecture':platform.machine(),'controller_python':sys.executable,
        'started_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
        'limitations':['API/host acceptance, not a rendered Tauri WebView test','Generated spots are not biological accuracy evidence']}
    host=None;started=time.monotonic()
    try:
        if args.transport_only:
            command=[sys.executable,'-m','pytest','-q','tests/test_platform_runtime.py','tests/test_sam_warm_pool.py',
                     'tests/test_sam_warm_worker.py','tests/test_sam_windows_transport.py']
            with (out/'transport-tests.log').open('xb') as log:
                result=subprocess.run(command,cwd=REPO,stdout=log,stderr=subprocess.STDOUT,timeout=90)
            require(result.returncode==0,'Native/transport tests failed')
            receipt.update(status='passed',mode='transport_only',native_windows=sys.platform=='win32',models_loaded=False)
        else:
            bundle=args.bundle.resolve();manifest=verify_bundle(bundle)
            runtime_query=subprocess.run([str(bundle_path(bundle,manifest['python'])),'-I','-B','-c',
                'import sys,platform,json;print(json.dumps({"executable":sys.executable,"version":sys.version,"platform":sys.platform,"machine":platform.machine()}))'],
                capture_output=True,text=True,timeout=10,check=True)
            receipt['actual_runtime']=json.loads(runtime_query.stdout)
            receipt.update(bundle=str(bundle),manifest_sha256=sha(bundle/'bundle-manifest.json'),
                           bundled_python=str(bundle_path(bundle,manifest['python'])),bundle_platform=manifest['platform'],
                           app_version=manifest['app_version'],bundle_files_verified=len(manifest['files']))
            if args.continue_from:
                receipt['offline_export_recheck']=verify_saved_exports(args.continue_from.resolve(),args.prior_receipt_sha256)
                receipt['limitations'].append('Prior model results belong to the prior manifest; continuation does not rerun inference or prove native busy-close')
            else:
                image_dir=out/'synthetic-inputs';image_dir.mkdir();images,pillow=synthetic_images(image_dir)
                receipt.update(pillow=pillow,inputs=[{**r,'path':str(r['path'])} for r in images])
            temp_root=out/'session-temp';temp_root.mkdir()
            host=Host(bundle,manifest,out/'launch-001',temp_root)
            host.start()
            receipt['ready_seconds']=host.startup_seconds
            if args.continue_from:
                host.client.request('GET','/api/batches',status=403)
                host.client.request('GET','/?desktop_session='+host.session)
                require(host.client.request('GET','/api/batches')['batches']==[],'Fresh continuation did not start empty')
                receipt['workflow']={'empty_batches':True,'models_requested':False}
            else:
                receipt['workflow']=exercise(host,images,'synthetic-acceptance')
                receipt['real_model_requests']=2
            receipt['real_model_request_attempts']=host.client.preview_attempts
            host.shutdown();receipt['shutdown']=host.cleanup
            host.close();host=None
            host=Host(bundle,manifest,out/'launch-002',temp_root);host.start()
            host.client.request('GET','/?desktop_session='+host.session)
            require(host.client.request('GET','/api/batches')['batches']==[],'Restart restored previous session')
            host.shutdown();receipt['restart']={'empty_batches':True,**host.cleanup}
            receipt.update(status='passed',mode='offline_export_and_empty_lifecycle_only' if args.continue_from else 'two_image_real_SAM',model_inference_offline=True,
                recipe_unchanged=True,peak_memory='not exposed by API; provider retains its original budget')
    except Exception as exc:
        receipt['error_type']=type(exc).__name__;receipt['error']=str(exc)
    finally:
        close_host(host,receipt)
        receipt['elapsed_seconds']=time.monotonic()-started
        receipt['files']={p.relative_to(out).as_posix():sha(p) for p in sorted(out.rglob('*')) if p.is_file()}
        save(out/'result.json',receipt)
    print(json.dumps({'status':receipt['status'],'receipt':str(out/'result.json'),'sha256':sha(out/'result.json')}))
    return 0 if receipt['status']=='passed' else 1


if __name__=='__main__':
    raise SystemExit(main())
