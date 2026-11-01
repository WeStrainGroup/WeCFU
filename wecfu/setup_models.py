"""Install only fixed official assets; never access user photographs or labels."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
from . import runtime_paths as paths


def _copy_verified(stream,destination,sha256,size):
    destination.parent.mkdir(parents=True,exist_ok=True)
    if destination.exists():
        if destination.is_symlink() or destination.stat().st_size!=size or paths.digest(destination)!=sha256:
            raise RuntimeError('Existing asset differs; it was not overwritten: '+str(destination))
        return
    fd,name=tempfile.mkstemp(prefix='.asset-',dir=destination.parent)
    temporary=Path(name); h=hashlib.sha256();total=0
    try:
        with os.fdopen(fd,'wb') as out:
            while block:=stream.read(1024**2):
                total+=len(block)
                if total>size: raise RuntimeError('Asset exceeds its pinned size')
                h.update(block);out.write(block)
            out.flush();os.fsync(out.fileno())
        if total!=size or h.hexdigest()!=sha256:raise RuntimeError('Official asset digest or size differs')
        # Link is exclusive and atomic; never replace an existing model.
        os.link(temporary,destination)
    finally: temporary.unlink(missing_ok=True)


def setup(cache,offline_from=None):
    cache=Path(cache).expanduser().resolve();cache.mkdir(parents=True,exist_ok=True)
    manifest=paths.asset_manifest()
    for row in manifest['assets']:
        destination=cache/row['path']
        if destination.exists():
            if destination.is_symlink() or destination.stat().st_size!=row['bytes'] or paths.digest(destination)!=row['sha256']:
                raise RuntimeError('Existing asset differs: '+row['path'])
            continue
        if offline_from is not None:
            source=Path(offline_from)/row['offline_path']
            with source.open('rb') as stream:_copy_verified(stream,destination,row['sha256'],row['bytes'])
        else:
            with urllib.request.urlopen(row['url'],timeout=60) as stream:
                _copy_verified(stream,destination,row['sha256'],row['bytes'])
    source_manifest=manifest['sam_source'];dest=cache/'sam2/source'
    required=source_manifest['files_sha256']
    if offline_from is not None:
        for rel,sha in required.items():
            source=Path(offline_from)/'sam2/source'/rel
            with source.open('rb') as stream:_copy_verified(stream,dest/rel,sha,source_manifest['files_bytes'][rel])
    elif not all((dest/rel).is_file() and paths.digest(dest/rel)==sha for rel,sha in required.items()):
        # Only named regular files are extracted. Tar member paths never choose output paths.
        with tempfile.TemporaryFile() as archive:
            with urllib.request.urlopen(source_manifest['url'],timeout=60) as response:
                size=0
                while block:=response.read(1024**2):
                    size+=len(block)
                    if size>64*1024**2:raise RuntimeError('SAM source archive exceeds 64 MiB')
                    archive.write(block)
            archive.seek(0)
            with tarfile.open(fileobj=archive,mode='r:gz') as tar:
                selected={}
                for member in tar.getmembers():
                    parts=PurePosixPath(member.name).parts
                    rel='/'.join(parts[1:])
                    if rel in required:
                        if not member.isfile() or rel in selected:raise RuntimeError('Unsafe or repeated source archive entry')
                        selected[rel]=member
                if set(selected)!=set(required):raise RuntimeError('Source archive omitted a pinned file')
                for rel,member in selected.items():
                    with tar.extractfile(member) as stream:
                        _copy_verified(stream,dest/rel,required[rel],source_manifest['files_bytes'][rel])
    return check(cache)


def check(cache):
    cache=Path(cache).expanduser().resolve();manifest=paths.asset_manifest();count=0
    for row in manifest['assets']:
        p=cache/row['path']
        if not p.is_file() or p.is_symlink() or p.stat().st_size!=row['bytes'] or paths.digest(p)!=row['sha256']:
            raise RuntimeError('Missing or changed asset: '+row['path'])
        count+=1
    for rel,sha in manifest['sam_source']['files_sha256'].items():
        p=cache/'sam2/source'/rel
        if not p.is_file() or p.is_symlink() or paths.digest(p)!=sha:raise RuntimeError('Missing or changed SAM source: '+rel)
        count+=1
    return {'status':'all_pinned_assets_verified','verified_files':count,
            'manifest_sha256':paths.digest(paths.PACKAGE_ROOT/'model_assets.json'),
            'network_inference':False,'cache_dir':str(cache)}


def runtime_check(cache):
    """Check the configured model interpreter, without loading either model."""
    command = """import json,sys
if sys.platform not in ('darwin','linux'): raise RuntimeError('Local SAM/Fusion models require macOS or Linux; the core app remains available')
from wecfu.runtime_paths import check_versions,SAM_DEVICE,PACKAGE_ROOT,resolve_library_policy,digest
from wecfu.server.fusion_dino.dino_contract import verify_contract
versions=check_versions()
policy=json.loads((PACKAGE_ROOT/'server/fusion_dino/library-pins.json').read_text())
sources=resolve_library_policy(policy)
contract=PACKAGE_ROOT/'server/fusion_dino/runtime-contract.json'
verify_contract(digest(contract))
import torch
available=SAM_DEVICE=='cpu' or torch.backends.mps.is_available()
if not available: raise RuntimeError('Selected SAM device is unavailable; explicitly choose WECFU_SAM_DEVICE=cpu')
print(json.dumps({'status':'model_runtime_verified','python':'.'.join(map(str,sys.version_info[:3])),'versions':versions,'verified_library_source_files':len(sources),'sam_device':SAM_DEVICE,'dino_device':'cpu','models_loaded':False}))
"""
    env={**os.environ,'WECFU_MODEL_HOME':str(Path(cache).expanduser().resolve()),
         'PYTHONPATH':str(paths.PACKAGE_ROOT.parent),'PYTHONDONTWRITEBYTECODE':'1',
         'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1'}
    result=subprocess.run([str(paths.MODEL_PYTHON),'-B','-c',command],env=env,
                          capture_output=True,text=True,timeout=30,check=False)
    if result.returncode:
        raise RuntimeError('Model runtime check failed: '+result.stderr[-4000:])
    return json.loads(result.stdout)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache-dir',type=Path,default=paths.MODEL_HOME)
    parser.add_argument('--offline-from',type=Path,help='Read pinned assets from an existing official asset cache')
    parser.add_argument('--check',action='store_true',help='Verify assets without downloads')
    parser.add_argument('--runtime-check',action='store_true',help='Also verify the configured model interpreter and selected device without loading models')
    args=parser.parse_args()
    result=check(args.cache_dir) if args.check else setup(args.cache_dir,args.offline_from)
    if args.runtime_check:result['runtime']=runtime_check(args.cache_dir)
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
