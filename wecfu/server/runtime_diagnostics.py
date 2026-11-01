"""Bounded local error metadata/log tails only. Never copy source images or labels."""
from datetime import datetime,timezone
from pathlib import Path
import hashlib,json,math,os,re,sys
from uuid import uuid4
from wecfu.runtime_paths import MODEL_HOME
ROOT=MODEL_HOME.parent/'diagnostics'
LIMIT=512*1024
_PHASES={'fusion-preview','fusion-dino',*(f'local-worker:{s}' for s in ('prepare','infer','finish','features','classify'))}
_ERRORS={'RuntimeError','RuntimeUnavailable','ValueError','TypeError','KeyError','ImportError',
         'ModuleNotFoundError','OSError','FileNotFoundError','PermissionError','MemoryError',
         'TimeoutError','AssertionError','AttributeError','UnpicklingError','NotImplementedError'}
# Only these constant codes reach shared server logs. Never forward exception
# text, filenames, source bytes, arbitrary class names, or worker log lines.
_REASONS={
    'exceeded 120 seconds':'wall_limit','120-second deadline':'wall_limit',
    'shared deadline':'wall_limit','4 GiB memory budget':'rss_limit',
    'storage budget':'output_limit','memory monitor':'monitor_unavailable',
    'single-image resource/runtime failure':'dino_worker_failure',
    'Local model failed; no candidate':'sam_worker_failure',
    'network/subprocess/other photo or answer access forbidden':'dino_access_guard',
    'SAM2 preview is local-only':'sam_network_guard',
    'Fusion worker is offline':'fusion_access_guard',
    'No module named':'missing_module','cannot import name':'import_failure',
    'out of memory':'allocation_failure','not implemented for':'unsupported_operator',
    'fixed runtime':'runtime_version','fixed transformers runtime':'runtime_version',
    'fixed Pillow13 raster':'runtime_version','fixed model runtime requires':'runtime_version',
    'Runtime source integrity mismatch':'library_integrity','Runtime distribution version mismatch':'runtime_version',
    'actual class source':'class_source_identity','unknown initial global':'unexpected_safe_global',
    'missing or duplicate reviewed default global':'safe_global_inventory',
    'official export/definition object identity mismatch':'safe_global_identity',
    'unexpected checkpoint globals':'checkpoint_globals','Weights only load failed':'weights_only_load',
    'Unsupported global':'unsupported_checkpoint_global','tensor metadata mismatch':'tensor_metadata',
    '028 architecture identity':'architecture_identity','strict load returned incompatibilities':'strict_load',
    'logical byte/finite mismatch':'loaded_value_identity','exact numeric mismatch':'loaded_value_identity',
    'finite CPU inputs':'input_nonfinite','model output layout':'output_layout',
    'only expected padding -inf':'output_padding','official coordinate parity':'output_coordinates',
    'file SHA changed':'source_integrity','source unchanged':'source_integrity',
    'checkpoint unchanged':'checkpoint_integrity','nontrivial/invalid EXIF':'source_orientation',
}
_OUTCOMES={'success','monitor_unavailable','wall_limit','rss_limit','output_limit','image_watchdog',
           'handshake_failure','incomplete_image_sequence','peak_unavailable','rss_peak_exceeded_after_exit',
           'wall_limit_after_exit','child_failed','parent_budget'}
_NUMERIC=('returncode','elapsed_seconds','sampled_peak_rss_bytes','sampled_peak_resident_bytes',
          'wait4_peak_resident_bytes','child_CPU_seconds','output_bytes_observed','output_bytes_retained')


def safe_log_summary(value):
    """Lossy allowlisted operations summary; full diagnostics stay local."""
    texts=[value.get('message','')];worker_errors=[];resources={}
    tails=value.get('log_tails',{})
    for name in ('prepare.log','infer.log','finish.log','features.log','classify.log','dino/logs.json'):
        text=tails.get(name,{}).get('tail_utf8','')
        if type(text) is not str:continue
        texts.append(text)
        # Also handles escaped newlines in the bounded JSON log tail.
        found=re.findall(r'(?:^|\n|\\n)(?:[A-Za-z_][A-Za-z_0-9]*\.)*([A-Za-z_][A-Za-z_0-9]*):',text)
        known=[kind for kind in found if kind in _ERRORS]
        if known:worker_errors.append({'log':name,'error_type':known[-1]})
    try:
        resource=json.loads(tails.get('dino/resource.json',{}).get('tail_utf8','{}'))
        if type(resource) is dict:
            if resource.get('outcome') in _OUTCOMES:resources['outcome']=resource['outcome']
            for key in _NUMERIC:
                number=resource.get(key)
                if type(number) in (int,float) and math.isfinite(number):resources[key]=number
    except (TypeError,ValueError):pass
    details={key:number for key,number in value.get('details',{}).items()
             if key in _NUMERIC and type(number) in (int,float) and math.isfinite(number)}
    reasons=sorted({code for fragment,code in _REASONS.items()
                    if any(type(text) is str and fragment.lower() in text.lower() for text in texts)})
    return {'event':'wecfu_runtime_failure','diagnostic_id':value['diagnostic_id'],
            'phase':value['phase'] if value['phase'] in _PHASES else 'other',
            'error_type':value['error_type'] if value['error_type'] in _ERRORS else 'other',
            'reason_codes':reasons or ['unclassified'],'worker_errors':worker_errors,
            'resources':resources,'details':details,'raw_text_logged':False}


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
    try:
        print('WECFU_RUNTIME_DIAGNOSTIC '+json.dumps(safe_log_summary(value),allow_nan=False,separators=(',',':')),
              file=sys.stderr,flush=True)
    except Exception:
        pass  # Logging must never replace the original inference failure.
    return identifier


def error_detail(error):
    identifier=getattr(error,'diagnostic_id',None)
    return str(error)+(f' [diagnostic {identifier}]' if identifier else '')
