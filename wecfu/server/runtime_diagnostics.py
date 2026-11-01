"""Bounded local error metadata/log tails only. Never copy source images or labels."""
from datetime import datetime,timezone
from pathlib import Path
import hashlib,json,os
from uuid import uuid4
from wecfu.runtime_paths import MODEL_HOME
ROOT=MODEL_HOME.parent/'diagnostics'
LIMIT=512*1024


def preserve_failure(error,*,phase,folder=None,details=None):
    existing=getattr(error,'diagnostic_id',None)
    if existing:return existing
    identifier=uuid4().hex
    value={'schema_version':1,'diagnostic_id':identifier,'created_at_utc':datetime.now(timezone.utc).isoformat(),
           'phase':phase,'error_type':type(error).__name__,'message':str(error),
           'details':details or {},'log_tails':{},'images_or_human_references_copied':False}
    if folder is not None:
        folder=Path(folder)
        # Only preselected text worker logs and resource/failure diagnostics.
        allowed=[folder/name for name in ('prepare.log','infer.log','finish.log','features.log','classify.log','dino/resource.json','dino/failure.json','dino/logs.json')]
        for path in allowed:
            if not path.is_file() or path.is_symlink():continue
            with path.open('rb') as stream:
                stream.seek(0,2);size=stream.tell();stream.seek(max(0,size-8192));tail=stream.read(8192)
            value['log_tails'][str(path.relative_to(folder))]={'total_bytes':size,'tail_sha256':hashlib.sha256(tail).hexdigest(),'tail_utf8':tail.decode('utf8','replace'),'truncated':size>8192}
    raw=json.dumps(value,ensure_ascii=False,allow_nan=False,indent=2).encode()
    if len(raw)>LIMIT:raise ValueError('diagnostic exceeds fixed metadata limit')
    ROOT.mkdir(parents=True,exist_ok=True)
    with (ROOT/(identifier+'.json')).open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
    error.diagnostic_id=identifier
    return identifier


def error_detail(error):
    identifier=getattr(error,'diagnostic_id',None)
    return str(error)+(f' [diagnostic {identifier}]' if identifier else '')
