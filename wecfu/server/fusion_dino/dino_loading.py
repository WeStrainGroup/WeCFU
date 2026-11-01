"""Exact030/028 restricted loading primitives; all source/shape/value checks retained.
No experiment runner import, optimizer reconstruction, network, or author wrapper.
"""
from collections import defaultdict
from pathlib import Path
import argparse,hashlib,json,math,mmap,pickletools,sys,types
from dino_numeric import require,sha
from dino_contract import CHECKPOINT, runtime_paths
CHUNK=1024**2
FACTS={'checkpoint_load_attempts':0,'checkpoint_load_completed':0,'constructor_attempts':0,'constructor_completed':0,'strict_load_attempts':0,'strict_load_completed':0,'forward_attempts':0,'forward_completed':0}
def event(name):
    print(json.dumps({'event':name,'facts':FACTS}),file=sys.stderr,flush=True)

def tensor_metadata(torch,t,expected):
    require(type(t)is torch.Tensor,'exact Tensor required; subclass rejected')
    require(str(t.device)=='cpu' and t.layout==torch.strided and t.is_contiguous(),'CPU dense contiguous tensor required')
    require(list(t.shape)==expected['shape'] and str(t.dtype)==expected['dtype'] and t.numel()==math.prod(expected['shape']),'tensor metadata mismatch')

def fingerprint(torch,t):
    """At most1MiB value copy/finite temporary; never flatten a noncontiguous tensor."""
    require(str(t.device)=='cpu' and t.layout==torch.strided and t.is_contiguous() and sys.byteorder=='little','fixed dense CPU little-endian values')
    flat=t.detach().view(-1);step=max(1,CHUNK//t.element_size());digest=hashlib.sha256()
    for start in range(0,t.numel(),step):
        chunk=flat[start:start+step]
        if t.is_floating_point():require(bool(torch.isfinite(chunk).all().item()),'nonfinite value')
        digest.update(chunk.view(torch.uint8).numpy().tobytes())
    return {'shape':list(t.shape),'dtype':str(t.dtype),'numel':t.numel(),'logical_sha256':digest.hexdigest(),'finite':True}

def exact_values(torch,a,b,label):
    require(list(a.shape)==list(b.shape) and a.dtype==b.dtype,'comparison shape/dtype: '+label)
    fa=fingerprint(torch,a);fb=fingerprint(torch,b)
    require(fa==fb,'logical byte/finite mismatch: '+label)
    av=a.detach().view(-1);bv=b.detach().view(-1);step=max(1,CHUNK//a.element_size())
    for start in range(0,a.numel(),step):require(torch.equal(av[start:start+step],bv[start:start+step]),'exact numeric mismatch: '+label)
    return fa

def window7():return [[(i//7-j//7+6)*13+(i%7-j%7+6) for j in range(49)] for i in range(49)]

def validate_selected(torch,model,issues):
    groups=issues['potential_shared_target_alias_groups'];buffers=issues['unmapped_original_converter_buffers']
    require(len(groups)==6 and all(len(g['members'])==12 for g in groups) and len(buffers)==12,'fixed84 selected tensors')
    rows={};alias_results=[]
    for group in groups:
        members=group['members'];anchor=members[0]['source_key'];a=model[anchor];rows[anchor]=fingerprint(torch,a)
        for item in members[1:]:
            key=item['source_key'];rows[key]=exact_values(torch,a,model[key],anchor+' == '+key)
        alias_results.append({'source_keys':[x['source_key'] for x in members],'all12_exact_equal':True,'same_storage_identity':len({int(model[x['source_key']].untyped_storage()._cdata) for x in members})==1})
    expected=torch.tensor(window7(),dtype=torch.int64,device='cpu')
    for row in buffers:
        key=row['source_key'];rows[key]=exact_values(torch,model[key],expected,key+' == official window7 index')
    require(len(rows)==84,'unique selected keys')
    return {'selected_tensors':84,'bbox_pair_comparisons':66,'buffer_comparisons':12,'values':rows,'alias_groups':alias_results,'all_selected_values_valid':True}

def mapped_views(torch,source,targets,issues):
    """Apply audited symbolic graph as unit-step slicing, with exact storage identity."""
    rename={r['source_key']:r['proposed_target_key'] for r in issues['unmapped_original_converter_buffers']}
    exclude=set(issues['pooler_keys_without_HF_target']);out={};seen=set();excluded=[]
    for target,row in targets.items():
        key=row['source_key'];seen.add(key)
        if key in exclude:excluded.append(key);continue
        name=rename.get(target,target);require(name not in out,'duplicate target')
        original=source[key];spans=row['source_slice_intervals'];require(len(spans)==len(original.shape) and all(s[2]==1 for s in spans),'only rank-preserving unit slices')
        view=original[tuple(slice(*s) for s in spans)]
        offset=original.storage_offset()+sum(s[0]*stride for s,stride in zip(spans,original.stride()))
        require(view.untyped_storage()._cdata==original.untyped_storage()._cdata and view.storage_offset()==offset and view.stride()==original.stride(),'mapping must preserve source storage/stride/offset')
        tensor_metadata(torch,view,row);out[name]=view
    require(seen==set(source) and set(excluded)==exclude and len(excluded)==2,'complete source coverage/exact2 pooler exclusion')
    require(type(out)is dict and not hasattr(out,'_metadata'),'plain mapping without hidden load metadata')
    return out

def aliases_and_ids(model):
    params=dict(model.named_parameters(remove_duplicate=False));buffers=dict(model.named_buffers(remove_duplicate=False))
    return {name:id(value) for name,value in {**params,**buffers}.items()}

def strict_load(torch,model,mapped,expected,collect):
    require(torch.__future__.get_swap_module_params_on_conversion() is False,'swap module params must remain disabled')
    before=aliases_and_ids(model);initial=collect(model)
    require(initial['state']==expected['state'] and initial['alias_groups']==expected['alias_groups'] and initial['nonpersistent_buffers']==expected['nonpersistent_buffers'],'028 architecture identity')
    require(set(mapped)==set(expected['state']),'exact1056 mapped target names')
    FACTS['strict_load_attempts']+=1;event('strict_load_started')
    incompatible=model.load_state_dict(mapped,strict=True,assign=False)
    require(not incompatible.missing_keys and not incompatible.unexpected_keys,'strict load returned incompatibilities')
    FACTS['strict_load_completed']+=1;event('strict_load_completed')
    require(aliases_and_ids(model)==before,'load changed parameter/buffer objects')
    actual=collect(model);require(actual['alias_groups']==expected['alias_groups'] and actual['state']==expected['state'],'alias/shape changed after load')
    values={}
    for name,t in model.state_dict(keep_vars=True).items():values[name]=exact_values(torch,t,mapped[name],name)
    return {'strict':True,'assign':False,'swap':False,'missing_keys':[],'unexpected_keys':[],'object_identity_preserved':True,'alias_groups':actual['alias_groups'],'target_state':actual,'loaded_values':values,'all_loaded_values_finite_exact':True}

def restricted_load(torch,helper,pins):
    from torch._subclasses.fake_tensor import FakeTensorMode
    try:
        for name in ('torch','torch.serialization',FakeTensorMode.__module__,'argparse'):
            runtime_paths.verify_module_file(name)
        require(argparse.Namespace.__module__=='argparse' and argparse.Namespace.__new__ is object.__new__ and argparse.Namespace.__setattr__ is object.__setattr__ and not hasattr(argparse.Namespace,'__setstate__'),'only inert standard Namespace')
        with FakeTensorMode():isolation=helper.audit_and_clear_official_globals(torch.serialization,pins)
        require(torch.serialization.get_safe_globals()==[],'defaults reappeared after FakeTensor exit')
        require(set(torch.serialization.get_unsafe_globals_in_checkpoint(CHECKPOINT))=={'argparse.Namespace'},'unexpected checkpoint globals')
        require(torch.serialization.get_default_mmap_options()==mmap.MAP_PRIVATE,'only read-isolated private mmap')
        with torch.serialization.safe_globals([argparse.Namespace]):
            helper.require_namespace_only(torch.serialization);FACTS['checkpoint_load_attempts']+=1;event('real_mmap_load_started')
            checkpoint=torch.load(CHECKPOINT,weights_only=True,map_location='cpu',mmap=True)
            FACTS['checkpoint_load_completed']+=1;event('real_mmap_load_completed')
        require(torch.serialization.get_safe_globals()==[],'globals changed during load')
        from collections import OrderedDict
        require(type(checkpoint)is dict and set(checkpoint)=={'model','optimizer','lr_scheduler','epoch','args'} and type(checkpoint['model']) in (dict,OrderedDict),'fixed checkpoint root')
        model=checkpoint.pop('model');del checkpoint
        isolation['after_load_and_mode_exit']=[]
        return model,isolation
    finally:
        torch.serialization.clear_safe_globals();require(torch.serialization.get_safe_globals()==[],'final globals clear')

PICKLE_SHA = 'fa199a4387a2f2df2b179a252550742d3ab8965cc1a47c585494572609628fdb'

KNOWN_GLOBALS = {'argparse Namespace', 'collections OrderedDict', 'torch FloatStorage',
                 'torch LongStorage', 'torch._utils _rebuild_tensor_v2'}

OFFICIAL_NAMES = ('builtins.ArithmeticError', 'builtins.AssertionError', 'builtins.AttributeError', 'builtins.BaseException', 'builtins.BaseExceptionGroup', 'builtins.BlockingIOError', 'builtins.BrokenPipeError', 'builtins.BufferError', 'builtins.BytesWarning', 'builtins.ChildProcessError', 'builtins.ConnectionAbortedError', 'builtins.ConnectionError', 'builtins.ConnectionRefusedError', 'builtins.ConnectionResetError', 'builtins.DeprecationWarning', 'builtins.EOFError', 'builtins.EncodingWarning', 'builtins.Exception', 'builtins.ExceptionGroup', 'builtins.FileExistsError', 'builtins.FileNotFoundError', 'builtins.FloatingPointError', 'builtins.FutureWarning', 'builtins.GeneratorExit', 'builtins.ImportError', 'builtins.ImportWarning', 'builtins.IndentationError', 'builtins.IndexError', 'builtins.InterruptedError', 'builtins.IsADirectoryError', 'builtins.KeyError', 'builtins.KeyboardInterrupt', 'builtins.LookupError', 'builtins.MemoryError', 'builtins.ModuleNotFoundError', 'builtins.NameError', 'builtins.NotADirectoryError', 'builtins.NotImplementedError', 'builtins.OSError', 'builtins.OverflowError', 'builtins.PendingDeprecationWarning', 'builtins.PermissionError', 'builtins.ProcessLookupError', 'builtins.RecursionError', 'builtins.ReferenceError', 'builtins.ResourceWarning', 'builtins.RuntimeError', 'builtins.RuntimeWarning', 'builtins.StopAsyncIteration', 'builtins.StopIteration', 'builtins.SyntaxError', 'builtins.SyntaxWarning', 'builtins.SystemError', 'builtins.SystemExit', 'builtins.TabError', 'builtins.TimeoutError', 'builtins.TypeError', 'builtins.UnboundLocalError', 'builtins.UnicodeDecodeError', 'builtins.UnicodeEncodeError', 'builtins.UnicodeError', 'builtins.UnicodeTranslateError', 'builtins.UnicodeWarning', 'builtins.UserWarning', 'builtins.ValueError', 'builtins.Warning', 'builtins.ZeroDivisionError', 'torch._dynamo.decorators._DimRange', 'torch.distributed._mesh_layout._FlatLayout', 'torch.distributed._mesh_layout._MeshLayout', 'torch.distributed.device_mesh.DeviceMesh', 'torch.distributed.tensor.DTensor', 'torch.distributed.tensor._dtensor_spec.DTensorSpec', 'torch.distributed.tensor._dtensor_spec.ShardOrderEntry', 'torch.distributed.tensor._dtensor_spec.TensorMeta', 'torch.distributed.tensor.placement_types.Partial', 'torch.distributed.tensor.placement_types.Replicate', 'torch.distributed.tensor.placement_types.Shard', 'torch.distributed.tensor.placement_types._StridedShard', 'torch.nested._internal.nested_tensor.NestedTensor', 'torch.nested._internal.nested_tensor._rebuild_njt', 'traceback.FrameSummary', 'traceback.StackSummary')

def inspect_pickle(raw):
    require(len(raw) <= 512 * 1024 and sha(raw) == PICKLE_SHA, 'unexpected fixed pickle bytes')
    actual = set()
    for op, arg, _ in pickletools.genops(raw):
        require(op.name not in {'STACK_GLOBAL', 'EXT1', 'EXT2', 'EXT4', 'INST', 'OBJ'},
                'unsupported global construction; no dynamic allowlist')
        if op.name == 'GLOBAL': actual.add(arg)
    require(actual == KNOWN_GLOBALS, 'GLOBAL set changed; stop')
    return sorted(actual)

def audit_and_clear_official_globals(serialization, pins):
    """Inside FakeTensorMode: exact source-reviewed defaults, then remove all83.

    This is an identity audit before clearing, not a deserialization allowlist.
    No imports are performed from observed names or the checkpoint.
    """
    expected = pins['official_globals']
    require(set(expected) == set(OFFICIAL_NAMES), 'fixed reviewed default set changed')
    initial = serialization.get_safe_globals()
    require(type(initial) is list, 'unexpected safe-global representation')
    records = []
    for obj in initial:
        require(isinstance(obj, (type, types.FunctionType)), 'unexpected safe-global object or alias tuple')
        name = obj.__module__ + '.' + obj.__qualname__
        require(name in expected, 'unknown initial global; stop: ' + name)
        binding = expected[name]
        require(binding['declared_module'] + '.' + binding['attribute'] == name, 'declared identity map changed')
        require((binding['kind'] == 'function') == isinstance(obj, types.FunctionType), 'object kind changed')
        for prefix in ('declared', 'definition'):
            loaded = sys.modules.get(binding[prefix + '_module'])
            require(loaded is not None and getattr(loaded, binding['attribute'], None) is obj,
                    'official export/definition object identity mismatch: ' + name)
            if binding[prefix + '_module'] == 'builtins':
                require(binding['kind'] == 'builtin_exception' and loaded is sys.modules['builtins']
                        and obj.__module__ == 'builtins' and issubclass(obj, BaseException)
                        and getattr(loaded, '__file__', None) is None, 'native builtin identity mismatch')
            else:
                runtime_paths.verify_module_file(binding[prefix + '_module'])
        source, source_hash = runtime_paths.verify_module_file(binding['registration_module'])
        records.append({'name': name, 'declared_module': binding['declared_module'],
                        'definition_module': binding['definition_module'],
                        'registration_module': binding['registration_module'],
                        'registration_sha256': source_hash})
    require(len(records) == len(expected) and len({row['name'] for row in records}) == len(records)
            and {row['name'] for row in records} == set(expected), 'missing or duplicate reviewed default global')
    serialization.clear_safe_globals()
    require(serialization.get_safe_globals() == [], 'failed to clear library dynamic globals')
    return {'observed_inside_FakeTensorMode': sorted(records, key=lambda row: row['name']),
            'after_clear': [], 'removed_defaults_not_restored': True}

def require_namespace_only(serialization):
    actual = serialization.get_safe_globals()
    require(type(actual) is list and len(actual) == 1 and actual[0] is argparse.Namespace,
            'actual load allowlist must be exactly standard-library argparse.Namespace')

def collect_cpu(model):
    """Adapt027 collect_meta, with explicit CPU/storage metadata checks only."""
    params=dict(model.named_parameters(remove_duplicate=False));buffers=dict(model.named_buffers(remove_duplicate=False))
    state=model.state_dict(keep_vars=True);groups=defaultdict(list);stores={};rows={}
    for kind,values in [('parameter',params),('buffer',buffers)]:
        for name,value in values.items():
            require(str(value.device)=='cpu','final nonCPU '+kind+': '+name)
            require(str(value.dtype)=='torch.float32' if kind=='parameter' else str(value.dtype) in ('torch.float32','torch.int64','torch.bool'),'unexpected state dtype')
            groups[(kind,id(value))].append(name)
            storage=value.untyped_storage();identity=int(storage._cdata);size=int(storage.nbytes())
            require(identity>0 and size>=0,'storage identity/size')
            require(identity not in stores or stores[identity]==size,'shared storage size changed');stores[identity]=size
    for name,value in state.items():
        require(str(value.device)=='cpu' and (name in params or name in buffers),'state outside CPU parameters/buffers')
        rows[name]={'shape':list(value.shape),'dtype':str(value.dtype),'kind':'parameter' if name in params else 'buffer','device':'cpu'}
    nonpersistent={name:{'shape':list(v.shape),'dtype':str(v.dtype),'device':'cpu'} for name,v in buffers.items() if name not in state}
    aliases=[{'kind':kind,'names':sorted(names)} for (kind,_),names in groups.items() if len(names)>1]
    return {'state':rows,'nonpersistent_buffers':nonpersistent,'alias_groups':sorted(aliases,key=lambda x:x['names'][0]),'named_parameter_entries':len(params),'named_buffer_entries':len(buffers),'all_parameters_buffers_state_CPU':True,'unique_storage_count':len(stores),'unique_storage_bytes':sum(stores.values()),'storage_values_read_or_serialized':False}
