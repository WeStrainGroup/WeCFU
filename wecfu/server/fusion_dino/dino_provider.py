"""Isolated proposed single-image provider. No live product imports or edits.
Caller must supply an independently approved runtime-contract SHA and an exclusive
output directory. Function definition/import performs no inference or file reads.
"""
import json,threading,time
from pathlib import Path
from .dino_contract import *
from .dino_numeric import f32,point,corners
from . import process_monitor
_SLOT=threading.Lock()


def validate_output(result,image):
    require(all(result[k]==image[k] for k in image),'exact source metadata')
    require(result['status']=='ok' and result['method']==METHOD and result['checkpoint_sha256']==CHECKPOINT_SHA,'fixed model result')
    boxes=result['raw_queries']['boxes'];scores=result['raw_queries']['scores']
    import math
    require(len(boxes)==len(scores)==900,'all900 original queries')
    require(all(type(s) in (int,float) and math.isfinite(s) and 0<=s<=1 and f32(s)==s for s in scores),'finite float32 scores')
    require(all(type(b)is list and len(b)==4 and all(type(x)in(int,float) and math.isfinite(x) and 0<=x<=1 and f32(x)==x for x in b) for b in boxes),'finite normalized float32 boxes')
    kept=[i for i,s in enumerate(scores) if s>.25]
    require(result['kept_query_indices']==kept and result['count']==result['predicted_count']==len(kept),'strict original kept set/order')
    require(result['points']==[point(boxes[q],image['height'],image['width']) for q in kept],'original float32 pixel centers')
    require(result['official_boxes_xyxy']==[corners(boxes[q],image['height'],image['width']) for q in kept],'original unclipped boxes')
    require(len(result['text_labels'])==len(kept) and all(type(x)is str for x in result['text_labels']),'labels retained without filtering')
    require(result['input_ids']==[101,5701,1012,102] and result['no_NMS_ROI_or_label_filter'] is True,'caption/no semantic filtering')
    log=result['logits_summary'];require(log['shape']==[1,900,256] and log['dtype']=='torch.float32' and log['active_finite'] is True and log['padded_negative_infinity']==900*252 and type(log['sha256'])is str and len(log['sha256'])==64,'logits layout retained')
    require(result['postprocessor_exact'] is True and result['source_before']==result['source_after'] and result['source_before']['sha256']==image['sha256'],'postprocessor/source parity')
    return result


def predict_file(working_copy,sha256,width,height,metadata,out,approved_contract_sha,deadline=None):
    """Fresh one-image run -> {prediction, resources, seal_sha256}; failures stay recorded.

    metadata carries path plus optional view/person_id/medium/atmosphere/origin_cohort.
    It cannot affect the numeric recipe. out must not exist. The optional absolute
    monotonic deadline can only shorten the shared 120s walltime budget.
    """
    require(_SLOT.acquire(False),'another DINO preview is running')
    created=None
    try:
        started=time.monotonic();end=min(started+SECONDS,deadline) if deadline is not None else started+SECONDS
        verify_contract(approved_contract_sha)
        source=validate_request(working_copy,sha256,width,height,metadata);out=Path(out)
        require(not out.exists(),'exclusive fresh output; no cache reuse')
        image={**metadata,'sha256':sha256,'width':width,'height':height}
        out.mkdir(parents=True,exist_ok=False)
        created=out
        output_json(out/'request.json',{'working_copy':str(source),'image':image})
        remaining=end-time.monotonic();require(remaining>0,'whole-image deadline before worker')
        command=[str(PYTHON),'-B',str(HERE/'dino_worker.py'),'--request',str((out/'request.json').resolve()),'--approved-contract-sha',approved_contract_sha]
        resources,stdout,stderr=process_monitor.supervise(command,rss_bytes=MEMORY,wall_seconds=remaining,cpu_seconds=120,output_bytes=METADATA_LIMIT)
        output_json(out/'resource.json',resources)
        output_json(out/'logs.json',{'stdout':stdout.decode('utf8','replace'),'stderr':stderr.decode('utf8','replace')})
        require(resources['outcome']=='success' and time.monotonic()<=end,'single-image resource/runtime failure; no prediction success')
        rows=[json.loads(line)['row'] for line in stdout.splitlines() if line.startswith(b'{') and json.loads(line).get('kind')=='prediction']
        require(len(rows)==1,'exactly one new image forward')
        prediction=validate_output(rows[0],image)
        require(prediction['runtime_contract_sha256']==approved_contract_sha and prediction['new_model_forwards']==1,'bound fresh inference')
        output_json(out/'prediction.json',prediction)
        files={p.name:identity(p)['sha256'] for p in out.iterdir() if p.is_file()}
        whole_elapsed=time.monotonic()-started
        require(time.monotonic()<=end,'whole-image deadline after parsing, writing and payload hashes')
        parent_resource={'whole_image_seconds_before_seal':whole_elapsed,'deadline_monotonic':end,'child_rss_limit_bytes':MEMORY,'combined_parent_child_hard_RSS_limit':False}
        output_json(out/'parent-resource.json',parent_resource)
        files['parent-resource.json']=identity(out/'parent-resource.json')['sha256']
        require(time.monotonic()<=end,'whole-image deadline after final resource hash')
        output_json(out/'seal.json',{'status':'fresh_single_image_success','runtime_contract_sha256':approved_contract_sha,'files_sha256':files,'new_model_forwards':1,'human_labels_read':False,'whole_image_seconds_before_seal':time.monotonic()-started})
        return {'prediction':prediction,'resources':resources|{'parent':parent_resource},'seal_sha256':identity(out/'seal.json')['sha256']}
    except BaseException as exc:
        if created is not None and not (created/'failure.json').exists():
            output_json(created/'failure.json',{'status':'failed_no_prediction_success','error_type':type(exc).__name__,'message':str(exc),'runtime_contract_sha256':approved_contract_sha})
        raise
    finally:
        _SLOT.release()
