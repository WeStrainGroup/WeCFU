"""Single image official045 CPU inference adaptation. Preparation only until root approves.
No full research runner, author wrapper, fit/labels/evaluation, downloads or caches.
"""
import argparse,hashlib,io,json,os,socket,sys,time,types,zipfile
from pathlib import Path
from dino_contract import *
from dino_numeric import safe_raster,infer_output
import dino_loading as loading
import process_monitor


def deny(*args,**kwargs):raise RuntimeError('local DINO: network/subprocess/other photo or answer access forbidden')


def load_model(pins,contract,runtime_contract):
    import torch,numpy as np,PIL,tokenizers
    from PIL import Image
    require(torch.__version__.split('+',1)[0]=='2.14.1' and np.__version__=='2.5.4' and PIL.__version__=='13.0.0'
            and tokenizers.__version__=='0.22.2' and sys.byteorder=='little','fixed runtime')
    for name in ('torch','numpy','numpy._core._multiarray_umath','PIL.Image','PIL._imaging','tokenizers','tokenizers.tokenizers'):
        runtime_paths.verify_module_file(name)
    torch.set_num_threads(1);torch.set_num_interop_threads(1);torch.set_default_dtype(torch.float32)
    source,isolation=loading.restricted_load(torch,loading,contract['v3_pins'])
    metadata=contract['v3_metadata'];require(set(source)==set(metadata) and len(source)==938,'938 original source keys')
    for key,tensor in source.items():loading.tensor_metadata(torch,tensor,metadata[key])
    selected=loading.validate_selected(torch,source,contract['mapping_issues'])
    torch.load=deny;torch.jit.load=deny;torch.hub.load_state_dict_from_url=deny
    import transformers
    require(transformers.__version__=='4.57.6','fixed transformers runtime')
    from transformers import BertConfig,SwinConfig,GroundingDinoConfig,GroundingDinoForObjectDetection,BertTokenizerFast,GroundingDinoImageProcessor,GroundingDinoProcessor
    for cls in (GroundingDinoForObjectDetection,BertTokenizerFast,GroundingDinoImageProcessor,GroundingDinoProcessor):
        require(str(Path(sys.modules[cls.__module__].__file__)) in pins,'actual class source')
    values=read_json(HERE/'configuration.json',runtime_contract['files_sha256']['configuration.json'])
    config=GroundingDinoConfig(backbone_config=SwinConfig(**values['swin']),text_config=BertConfig(**values['bert']),**values['grounding_dino'])
    require(not config.use_pretrained_backbone and not config.use_timm_backbone and config.backbone is None,'offline config')
    torch.random.default_generator.manual_seed(20261030)
    prior_call=torch.nn.Module._call_impl;prior_profile=sys.getprofile();require(prior_profile is None,'existing profiler')
    def no_forward(*a,**k):raise RuntimeError('forward before strict load forbidden')
    def profile(frame,event_type,arg):
        if event_type=='call' and frame.f_code.co_name=='forward' and isinstance(frame.f_locals.get('self'),torch.nn.Module):no_forward()
    try:
        torch.nn.Module._call_impl=no_forward;sys.setprofile(profile)
        with torch.device('cpu'):model=GroundingDinoForObjectDetection(config)
        mapped=loading.mapped_views(torch,source,contract['mapping_targets'],contract['mapping_issues'])
        loaded=loading.strict_load(torch,model,mapped,contract['cpu_comparison'],loading.collect_cpu)
    finally:
        torch.nn.Module._call_impl=prior_call;sys.setprofile(prior_profile)
    del mapped,source
    require(loaded['all_loaded_values_finite_exact'] and selected['all_selected_values_valid'],'strict verified load')
    load_summary={'strict':True,'assign':False,'selected84_verified':True,'targets1056_verified':True,'alias_groups':loaded['alias_groups'],'loaded_value_digest':hashlib.sha256(json.dumps(loaded['loaded_values'],sort_keys=True,separators=(',',':')).encode()).hexdigest()}
    del loaded,selected
    model.eval();model.requires_grad_(False)
    tokenizer=BertTokenizerFast.from_pretrained(str(TOKENIZER),local_files_only=True,trust_remote_code=False,do_lower_case=True)
    image_processor=GroundingDinoImageProcessor(do_resize=True,size={'shortest_edge':800,'longest_edge':1333},resample=Image.Resampling.BILINEAR,do_rescale=True,rescale_factor=1/255,do_normalize=True,image_mean=[.485,.456,.406],image_std=[.229,.224,.225],do_pad=True,pad_size=None)
    processor=GroundingDinoProcessor(image_processor=image_processor,tokenizer=tokenizer)
    require(not image_processor.is_fast,'slow processor')
    return torch,Image,model,processor,load_summary


def run(request_path,pin):
    limits=process_monitor.cpu_limit(120)
    print(json.dumps({'kind':'ready','pid':os.getpid(),'cpu_limits':limits}),flush=True)
    require(sys.stdin.buffer.read(1)==b'G','parent resource monitor must authorize work')
    start=time.monotonic();runtime_contract=verify_contract(pin)
    req=read_json(request_path);require(set(req)=={'working_copy','image'},'request schema');row=req['image']
    source=validate_request(req['working_copy'],row['sha256'],row['width'],row['height'],{k:v for k,v in row.items() if k not in ('sha256','width','height')})
    before=identity(source,row['sha256'],INPUT_LIMIT)
    raw=source.read_bytes();require(hashlib.sha256(raw).hexdigest()==row['sha256'],'same hashed image bytes')
    policy=read_json(HERE/'library-pins.json',runtime_contract['files_sha256']['library-pins.json'])
    pins=runtime_paths.resolve_library_policy(policy)
    runtime_paths.verify_tokenizer()
    cp=identity(CHECKPOINT,CHECKPOINT_SHA)
    require(cp['size_bytes']==CHECKPOINT_BYTES,'fixed checkpoint byte size')
    contract=read_json(HERE/'loading-metadata.json',runtime_contract['files_sha256']['loading-metadata.json'])
    with zipfile.ZipFile(CHECKPOINT) as archive:
        names=[n for n in archive.namelist() if n.endswith('/data.pkl')]
        require(len(names)==1 and archive.getinfo(names[0]).file_size<=512*1024,'bounded fixed pickle')
        loading.inspect_pickle(archive.read(names[0]))
    os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1',CUDA_VISIBLE_DEVICES='',PYTORCH_ENABLE_MPS_FALLBACK='0',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',TOKENIZERS_PARALLELISM='false')
    socket.socket.connect=deny;socket.socket.connect_ex=deny;socket.create_connection=deny
    def audit(name,args):
        if name in ('socket.connect','socket.getaddrinfo','subprocess.Popen','os.system'):deny()
        if name=='open' and args and isinstance(args[0],(str,bytes,os.PathLike)):
            p=Path(os.fsdecode(args[0]));text=str(p).lower();parts={part.lower() for part in p.parts}
            if parts&{'references','human-review-archive','review-archives','evaluation-only'}:deny()
            if p.suffix.lower() in ('.jpg','.jpeg','.png','.tif','.tiff','.npz','.npy','.onnx','.safetensors') and p!=source:deny()
            if p.suffix.lower() in ('.pt','.pth','.pkl','.pickle') and p!=CHECKPOINT:deny()
    sys.addaudithook(audit)
    torch,Image,model,processor,load_summary=load_model(pins,contract,runtime_contract)
    image,orientation=safe_raster(Image,raw,row)
    inputs=processor(images=image,text='colony.',return_tensors='pt');image.close()
    require(inputs['pixel_values'].device.type=='cpu' and inputs['pixel_values'].dtype==torch.float32 and bool(torch.isfinite(inputs['pixel_values']).all()),'finite CPU inputs')
    with torch.inference_mode():outputs=model(**inputs)
    result=infer_output(torch,processor,outputs,inputs,row['height'],row['width'])
    result['resized_hw']=list(inputs['pixel_values'].shape[-2:]);del outputs,inputs,model
    after=identity(source,row['sha256'],INPUT_LIMIT);require(after==before,'source unchanged')
    require(identity(CHECKPOINT,CHECKPOINT_SHA)==cp,'checkpoint unchanged')
    for path,expected in pins.items():identity(path,expected)
    verify_contract(pin)
    result.update(row);result.update(status='ok',image_id=row['path'],method=METHOD,source_before=before,source_after=after,elapsed_seconds=time.monotonic()-start,checkpoint_sha256=CHECKPOINT_SHA,strict_load=load_summary,runtime_contract_sha256=pin,photo_or_answer_uploads=False,new_model_forwards=1)
    print(json.dumps({'kind':'prediction','row':result},allow_nan=False,separators=(',',':')),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--request',required=True);parser.add_argument('--approved-contract-sha',required=True);args=parser.parse_args()
    run(Path(args.request),args.approved_contract_sha)
