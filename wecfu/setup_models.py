"""Install only fixed official assets; never access user photographs or labels."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
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


def _install_sam_source(tar, destination, manifest):
    """Copy pinned bytes only; resolve upstream aliases inside this archive.

    Official SAM archives include legacy YAML symlinks. Never extract those
    links onto disk or let tarfile resolve them implicitly against a filesystem.
    """
    root = 'sam2-' + manifest['commit']
    members = {}
    for member in tar.getmembers():
        name = member.name.rstrip('/')
        parts = PurePosixPath(name).parts
        if (not parts or parts[0] != root or name.startswith('/') or '\\' in name
                or '..' in parts or posixpath.normpath(name) != name):
            raise RuntimeError('Unsafe SAM source archive path: ' + member.name)
        if name in members:
            raise RuntimeError('Repeated SAM source archive entry: ' + name)
        members[name] = member
    selected = {}
    for rel, digest in manifest['files_sha256'].items():
        parts = PurePosixPath(rel).parts
        if not parts or rel.startswith('/') or '\\' in rel or '..' in parts or posixpath.normpath(rel) != rel:
            raise RuntimeError('Unsafe pinned SAM source path')
        name = root + '/' + rel
        seen = set()
        while True:
            if name in seen or len(seen) >= 16:
                raise RuntimeError('Cyclic or excessive SAM source alias: ' + rel)
            seen.add(name)
            member = members.get(name)
            if member is None:
                raise RuntimeError('Source archive omitted a pinned file or alias target: ' + rel)
            if member.isfile():
                if member.size != manifest['files_bytes'][rel]:
                    raise RuntimeError('SAM source member differs from pinned size: ' + rel)
                selected[rel] = member
                break
            if not (member.issym() or member.islnk()):
                raise RuntimeError('SAM source alias must end at a regular file: ' + rel)
            target = member.linkname
            if not target or target.startswith('/') or '\\' in target:
                raise RuntimeError('Unsafe SAM source alias target: ' + rel)
            # Symlinks are relative to their directory; hardlinks use archive names.
            name = posixpath.normpath(posixpath.join(posixpath.dirname(name), target)
                                     if member.issym() else target)
            if not name.startswith(root + '/'):
                raise RuntimeError('SAM source alias escapes the fixed archive root: ' + rel)
    for rel, member in selected.items():
        # member is now a unique regular entry. Output names come only from pins.
        with tar.extractfile(member) as stream:
            _copy_verified(stream, destination/rel, manifest['files_sha256'][rel],
                           manifest['files_bytes'][rel])


def _asset_rows(manifest, profile):
    if profile not in ("sam", "all"):
        raise ValueError("Unknown model setup profile")
    return [row for row in manifest["assets"] if profile == "all" or row["path"].startswith("sam2/")]


def setup(cache,offline_from=None, *, profile="sam"):
    cache=Path(cache).expanduser().resolve();cache.mkdir(parents=True,exist_ok=True)
    manifest=paths.asset_manifest()
    for row in _asset_rows(manifest, profile):
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
        # Only pinned regular bytes are copied; archive links never reach disk.
        with tempfile.TemporaryFile() as archive:
            with urllib.request.urlopen(source_manifest['url'],timeout=60) as response:
                size=0
                while block:=response.read(1024**2):
                    size+=len(block)
                    if size>64*1024**2:raise RuntimeError('SAM source archive exceeds 64 MiB')
                    archive.write(block)
            archive.seek(0)
            with tarfile.open(fileobj=archive,mode='r:gz') as tar:
                _install_sam_source(tar,dest,source_manifest)
    return check(cache, profile=profile)


def check(cache, *, profile="sam"):
    cache=Path(cache).expanduser().resolve();manifest=paths.asset_manifest();count=0
    for row in _asset_rows(manifest, profile):
        p=cache/row['path']
        if not p.is_file() or p.is_symlink() or p.stat().st_size!=row['bytes'] or paths.digest(p)!=row['sha256']:
            raise RuntimeError('Missing or changed asset: '+row['path'])
        count+=1
    for rel,sha in manifest['sam_source']['files_sha256'].items():
        p=cache/'sam2/source'/rel
        if not p.is_file() or p.is_symlink() or paths.digest(p)!=sha:raise RuntimeError('Missing or changed SAM source: '+rel)
        count+=1
    return {'status':'all_pinned_assets_verified','verified_files':count,
            'manifest_sha256':paths.digest(paths.PACKAGE_ROOT/'model_assets.json'), 'profile':profile,
            'network_inference':False,'cache_dir':str(cache)}


def runtime_check(cache, *, profile="sam"):
    """Check the configured model interpreter, without loading either model."""
    if profile == "sam":
        from .runtime_bootstrap import _probe
        env = {**{k:v for k,v in os.environ.items() if k != 'PYTHONHOME'},
               'PYTHONPATH':str(paths.PACKAGE_ROOT.parent),'PYTHONDONTWRITEBYTECODE':'1',
               'PYTHONNOUSERSITE':'1','WECFU_SAM_DEVICE':paths.SAM_DEVICE,'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1'}
        result = _probe(paths.MODEL_PYTHON, cache, env=env)
        return {'status':'model_runtime_verified','models_loaded':False,**result}
    command = """import json,sys,os
if sys.platform not in ('darwin','linux'): raise RuntimeError('Ultra requires macOS or Linux')
from wecfu.runtime_paths import check_versions,SAM_DEVICE,SAM_SOURCE,verify_sam_source
versions=check_versions()
verify_sam_source()
import torch,torchvision,numpy,PIL,hydra,omegaconf,iopath
sys.path.insert(0,str(SAM_SOURCE))
from sam2 import build_sam,automatic_mask_generator
available=SAM_DEVICE=='cpu' or torch.backends.mps.is_available()
if not available: raise RuntimeError('Selected SAM device is unavailable; choose WECFU_SAM_DEVICE=cpu')
print(json.dumps({'status':'model_runtime_verified','python':'.'.join(map(str,sys.version_info[:3])),'versions':versions,'sam_device':SAM_DEVICE,'models_loaded':False}))
"""
    if profile == "all":
        command = command.replace("import torch,torchvision,numpy,PIL,hydra,omegaconf,iopath", """from wecfu.runtime_paths import PACKAGE_ROOT,resolve_library_policy,digest
from wecfu.server.fusion_dino.dino_contract import verify_contract
policy=json.loads((PACKAGE_ROOT/'server/fusion_dino/library-pins.json').read_text())
resolve_library_policy(policy)
verify_contract(digest(PACKAGE_ROOT/'server/fusion_dino/runtime-contract.json'))
import torch,torchvision,numpy,PIL,hydra,omegaconf,iopath""")
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
    parser.add_argument('--profile',choices=('sam','all'),default='sam',help='SAM for Ultra; all also installs legacy Fusion assets')
    parser.add_argument('--cache-dir',type=Path,default=paths.MODEL_HOME)
    parser.add_argument('--offline-from',type=Path,help='Read pinned assets from an existing official asset cache')
    parser.add_argument('--check',action='store_true',help='Verify assets without downloads')
    parser.add_argument('--runtime-check',action='store_true',help='Also verify the configured model interpreter and selected device without loading models')
    args=parser.parse_args()
    result=check(args.cache_dir,profile=args.profile) if args.check else setup(args.cache_dir,args.offline_from,profile=args.profile)
    if args.runtime_check:result['runtime']=runtime_check(args.cache_dir,profile=args.profile)
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
