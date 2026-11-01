"""Pinned local-only provider contract. Import does not read weights or photos."""
from pathlib import Path
import hashlib,json,os,stat,time,sys
HERE=Path(__file__).resolve().parent
REPO=HERE.parents[2]
sys.path.insert(0,str(REPO))
from wecfu import runtime_paths
PYTHON=runtime_paths.MODEL_PYTHON
CHECKPOINT=runtime_paths.DINO_CHECKPOINT
CHECKPOINT_SHA='af2e3769e6f1512f4dabb3043b6b4a5de97935549eaa843bfa3074728ce630ea'
CHECKPOINT_BYTES=1199389264
TOKENIZER=runtime_paths.TOKENIZER
METHOD='licensed_colony_grounding_dino_official_cpu_colony025_r1'
MEMORY=4*1024**3
SECONDS=120
METADATA_LIMIT=32*1024**2
INPUT_LIMIT=32*1024**2
PIXEL_LIMIT=36_000_000

def require(ok,message):
    if not ok:raise ValueError(message)

def identity(path,expected_sha=None,maximum=None):
    path=Path(path);before=path.stat()
    require(stat.S_ISREG(before.st_mode) and (maximum is None or before.st_size<=maximum),'regular bounded file')
    h=hashlib.sha256()
    with path.open('rb') as f:
        opened=os.fstat(f.fileno())
        for b in iter(lambda:f.read(1024**2),b''):h.update(b)
        closed=os.fstat(f.fileno())
    after=path.stat();fields=lambda s:[s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns]
    require(fields(before)==fields(opened)==fields(closed)==fields(after),'file identity changed during hash')
    digest=h.hexdigest();require(expected_sha is None or digest==expected_sha,'file SHA changed')
    return {'sha256':digest,'size_bytes':before.st_size,'fingerprint':fields(before)}

def read_json(path,expected_sha=None):
    pin=identity(path,expected_sha,METADATA_LIMIT);raw=Path(path).read_bytes()
    require(hashlib.sha256(raw).hexdigest()==pin['sha256'],'JSON changed during read')
    return json.loads(raw)

def verify_contract(approved_contract_sha):
    contract=read_json(HERE/'runtime-contract.json',approved_contract_sha)
    require(contract['method']==METHOD and contract['checkpoint_sha256']==CHECKPOINT_SHA,'fixed detector contract')
    require(contract['model_parameters']=={'device':'cpu','dtype':'float32','threads':1,'caption':'colony.','threshold_strict_gt':.25,'text_threshold':.25,'resize_shortest':800,'resize_longest':1333,'queries':900},'fixed science')
    for rel,pin in contract['files_sha256'].items():
        require(Path(rel).name==rel,'flat source contract')
        identity(HERE/rel,pin,METADATA_LIMIT)
    for rel,pin in contract.get('package_files_sha256',{}).items():
        require(Path(rel).name==rel,'flat public package contract')
        identity(runtime_paths.PACKAGE_ROOT/rel,pin,METADATA_LIMIT)
    return contract

def output_json(path,value):
    raw=json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()
    require(len(raw)<=METADATA_LIMIT,'metadata bound')
    with Path(path).open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())

def validate_request(working_copy,sha256,width,height,metadata):
    import re
    require(type(sha256)is str and re.fullmatch('[0-9a-f]{64}',sha256) is not None,'source SHA256')
    require(type(width)is int and type(height)is int and width>0 and height>0 and width*height<=PIXEL_LIMIT,'bounded positive raster dimensions')
    require(type(metadata)is dict and set(metadata)<={'path','view','person_id','medium','atmosphere','origin_cohort'} and type(metadata.get('path'))is str and metadata['path'],'metadata-only identity')
    require(all(v is None or type(v)is str for v in metadata.values()),'plain metadata strings only')
    source=Path(working_copy).resolve(strict=True)
    require(not ({p.lower() for p in source.parts}&{'references','human-review-archive','review-archives','evaluation-only'}),'no human answer paths')
    return source
