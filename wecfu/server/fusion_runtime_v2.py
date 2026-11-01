"""Public SAM+DINO+frozen-filter preview; no human reference or fitting APIs."""
from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
import hashlib,json,os,tempfile,time
from . import sam_runtime, runtime_diagnostics
from .fusion_dino import dino_provider,dino_contract

ENGINE='sam_dino_fusion_local_v2'
RECIPE_ID='sam_dino_raw10_threshold075_auto095_v2'
ANNOTATION_KIND='SAM_D0_plus_box_derived_center_rings'
PLATE_INSET=.95
TIMEOUT_SECONDS=120.
HERE=Path(__file__).resolve().parent
AUTHORIZATION=HERE/'product_fusion_v2.json'
FILTER=HERE/'fusion_filter_v2.json'
WORKER=HERE/'fusion_worker_v2.py'
FILTER_SHA256='7542a3b5f3bfe28e7077ee478b944044daf56246a463ec8e9507209ea4c42570'
MODEL_SHA256='fc7ab851da6d09daf36bc49ac1d6e2aec52a6a04f982c588017704805f638209'
DETECTOR_CONTRACT_SHA256='d63350bf0033776eb13a519a717d4dd7ade08eed552d20ccc393e8c663b21275'
SOURCE_FILES=('fusion_worker_v2.py','fusion_dino/fusion_math_v2.py',
              'fusion_dino/fusion_math.py','fusion_dino/appearance_runtime.py')
RuntimeUnavailable=sam_runtime.RuntimeUnavailable


def require(ok,msg):
    if not ok:raise RuntimeUnavailable(msg)


def view_for_source(image_sha256,declaration=None):
    require(type(declaration) is dict and declaration.get('declared') is True
            and declaration.get('source_sha256')==image_sha256,
            'Declare the view of this exact image before using Fusion v2')
    require(declaration.get('view') in ('main','blank'),
            'Fusion v2 requires a declared front or blank dish photo; back/unknown views are unsupported')
    return declaration['view']


class LocalFusionProvider:
    def __init__(self,*,web_mode=False):
        self.timeout_seconds=180. if web_mode else TIMEOUT_SECONDS
        self.enabled=os.environ.get('WECFU_ENABLE_FUSION_V2','1')=='1'
        self.sam=sam_runtime.LocalSamProvider(web_mode=web_mode,enable_for_fusion=True)
        # The default Fusion v2 product includes the unchanged SAM stage.
        if self.enabled:
            self.sam.enabled = True

    def require_available(self):
        require(self.enabled,'Fusion v2 is disabled; no fallback model will run')
        try:
            authority=dino_contract.read_json(AUTHORIZATION)
            require(authority.get('product_runtime') is True and authority.get('engine')==ENGINE and authority.get('recipe_id')==RECIPE_ID,'Fusion v2 product manifest differs')
            require(authority['detector_contract_sha256']==DETECTOR_CONTRACT_SHA256 and authority['sam_model_sha256']==sam_runtime.MODEL_SHA256 and authority['dino_model_sha256']==dino_contract.CHECKPOINT_SHA,'Fusion model recipe differs')
            dino_contract.verify_contract(DETECTOR_CONTRACT_SHA256)
            require(authority['filter_artifact_sha256']==FILTER_SHA256 and authority['model_sha256']==MODEL_SHA256,'Approved Fusion v2 parameter identity differs')
            artifact=dino_contract.read_json(FILTER,FILTER_SHA256)
            model=artifact['model']
            from .fusion_dino import fusion_math_v2
            fusion_math_v2.validate_product_model(model)
            require(artifact['recipe_id']==RECIPE_ID and hashlib.sha256(json.dumps(model,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()==MODEL_SHA256,'Fixed numerical model changed')
            require(set(authority['source_files_sha256'])==set(SOURCE_FILES),'Complete Fusion v2 source manifest required')
            for relative,pin in authority['source_files_sha256'].items():
                require(not Path(relative).is_absolute() and '..' not in Path(relative).parts,'Product source path must be relative')
                dino_contract.identity(HERE/relative,pin)
            require(dino_contract.CHECKPOINT.is_file() and dino_contract.CHECKPOINT.stat().st_size==dino_contract.CHECKPOINT_BYTES,'Fixed local DINO weights missing; no download is attempted')
            self.sam.require_available()
            return authority,artifact
        except RuntimeUnavailable:raise
        except (OSError,ValueError,KeyError,TypeError) as exc:
            raise RuntimeUnavailable('Fusion v2 runtime or fixed parameters are missing/changed. Run python -m wecfu.setup_models; no fallback was run.') from exc

    def capability(self):
        reason=None;authority={}
        try:authority,_=self.require_available()
        except RuntimeUnavailable as exc:reason=str(exc)
        return dict(enabled=self.enabled,available=reason is None,reason=reason,engine=ENGINE,
                    model_sha256=MODEL_SHA256,recipe_id=RECIPE_ID,label='Fusion v2',
                    plate_inset=PLATE_INSET,sam_model_sha256=sam_runtime.MODEL_SHA256,
                    dino_model_sha256=dino_contract.CHECKPOINT_SHA,annotation_kind=ANNOTATION_KIND,
                    feature_projection=[0,1,2,5,6,7,8,9,10,11],D0_exclusion_fraction=.025,coordinate_method='raw_DINO_unchanged',
                    requires_automatic_plate=True,supported_views=['main','blank'],
                    requires_source_view_declaration=True,default_model=True,fallback=False,
                    wall_timeout_seconds=self.timeout_seconds)

    def predict(self,payload,plate,image_sha256,width,height,view,*,deadline=None):
        started=time.monotonic();deadline=min(started+self.timeout_seconds,deadline) if deadline is not None else started+self.timeout_seconds
        require(view in ('main','blank'),'Fusion supports front and blank images only; back images are separate')
        require(hashlib.sha256(payload).hexdigest()==image_sha256,'Fusion source bytes changed')
        authority,artifact=self.require_available()
        require(time.monotonic()<deadline,'Fusion preview exceeded its shared deadline')
        # SAM completes and its child is reaped before DINO starts.
        original,sam_raw=self.sam.predict(payload,plate,image_sha256,deadline=deadline)
        with tempfile.TemporaryDirectory(prefix='wecfu-fusion-preview-') as tmp:
            folder=Path(tmp);source=folder/'source.image';source.write_bytes(payload);source.chmod(0o400)
            image={'path':'current-image','sha256':image_sha256,'width':width,'height':height,'view':view,'automatic_plate':asdict(plate)}
            try:
                result=dino_provider.predict_file(source,image_sha256,width,height,{'path':'current-image','view':view},folder/'dino',DETECTOR_CONTRACT_SHA256,deadline=deadline)
            except Exception as exc:
                try: runtime_diagnostics.preserve_failure(exc, phase="fusion-dino", folder=folder)
                except Exception: pass
                raise
            dino=result['prediction']
            require(time.monotonic()<deadline,'Fusion preview exceeded its shared deadline after DINO')
            # The product copy contains only prediction parameters; no training IDs/labels.
            (folder/'filter.json').write_bytes(FILTER.read_bytes())
            dino_contract.identity(folder/'filter.json',authority['filter_artifact_sha256'])
            baseline={'path':'current-image','sha256':image_sha256,'points':[[x['cx'],x['cy']] for x in original]}
            request={'image':image,'baseline':baseline,'baseline_circles':original,'filter_artifact_sha256':authority['filter_artifact_sha256'],
                     'dino_prediction_sha256':dino_contract.identity(folder/'dino/prediction.json')['sha256']}
            dino_contract.output_json(folder/'fusion-request.json',request)
            env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','PYTHONPATH':str(sam_runtime.REPO),
                 'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1',
                 'OPENBLAS_NUM_THREADS':'1','VECLIB_MAXIMUM_THREADS':'1'}
            for executable,stage in ((sam_runtime.SAM_PYTHON,'features'),(sam_runtime.CV_PYTHON,'classify')):
                sam_runtime.run_stage([str(executable),'-B',str(WORKER),str(folder),stage],folder,deadline,env)
            final=dino_contract.read_json(folder/'fusion-result.json')
            require(final['status']=='ok' and final['image_sha256']==image_sha256 and final['filter_artifact_sha256']==authority['filter_artifact_sha256'],'Fusion result source binding changed')
            require(final['detections'][:len(original)]==original and final['d0_count']==len(original) and final['supplemental_count']==len(final['detections'])-len(original),'Fusion must preserve all D0 marks exactly')
            after,_=self.require_available();require(after==authority,'Fusion binding changed while inference ran')
            require(time.monotonic()<deadline,'Fusion preview exceeded its shared deadline; no partial result')
            raw_count=sam_raw+dino['count']
            provenance={k:authority[k] for k in ('model_sha256','filter_artifact_sha256','sam_model_sha256','dino_model_sha256','detector_contract_sha256')}
            provenance.update(recipe_id=RECIPE_ID,image_sha256=image_sha256,plate_inset=.95,automatic_plate=asdict(plate),raw_count=raw_count,
                              candidate_count=len(final['detections']),d0_count=len(original),supplemental_count=final['supplemental_count'],raw_dino_count=dino['count'],annotation_kind=ANNOTATION_KIND)
            provenance.update(source_view=view,feature_projection=[0,1,2,5,6,7,8,9,10,11],coordinate_method='raw_DINO_unchanged',
                              D0_exclusion_fraction=.025,DINO_dedup_fraction=.005,ROI_max_radial=.95)
            return final['detections'],raw_count,provenance
