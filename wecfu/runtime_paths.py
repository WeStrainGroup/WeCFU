"""Public, relocatable model assets and distribution-integrity policy.

Inference is offline. Setup alone may download pinned public assets. Installed
Python/OS are trusted; third-party modules are verified against wheel/conda
RECORD digests and the frozen source digests where available. Native artifacts
are platform-specific, never matched to another machine's dylib hashes.
"""
from __future__ import annotations
import base64
import hashlib
import importlib.metadata as metadata
import json
import os
import platform
from pathlib import Path
import sys
import sysconfig
from . import platform_runtime

PACKAGE_ROOT = Path(__file__).resolve().parent

def model_home():
    if os.environ.get('WECFU_MODEL_HOME'):
        return Path(os.environ['WECFU_MODEL_HOME']).expanduser().resolve()
    return platform_runtime.default_model_home()

MODEL_HOME = model_home()
from .runtime_bootstrap import prepared_python
_DEFAULT_PYTHON = str(prepared_python(MODEL_HOME) or sys.executable)
MODEL_PYTHON = Path(os.environ.get('WECFU_MODEL_PYTHON', _DEFAULT_PYTHON)).expanduser().absolute()
CV_PYTHON = Path(os.environ.get('WECFU_CV_PYTHON', _DEFAULT_PYTHON)).expanduser().absolute()
SAM_DEVICE = os.environ.get('WECFU_SAM_DEVICE', 'mps' if sys.platform == 'darwin' and platform.machine() == 'arm64' else 'cpu')
if SAM_DEVICE not in ('mps', 'cpu'):
    raise ValueError('WECFU_SAM_DEVICE must explicitly select mps or cpu')
SAM_SOURCE = MODEL_HOME/'sam2/source'
SAM_CHECKPOINT = MODEL_HOME/'sam2/sam2.1_hiera_tiny.pt'
DINO_CHECKPOINT = MODEL_HOME/'colony-grounded-sam2/colony_gd.pth'
TOKENIZER = MODEL_HOME/'bert-tokenizer'


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024**2), b''): h.update(block)
    return h.hexdigest()


def asset_manifest():
    return json.loads((PACKAGE_ROOT/'model_assets.json').read_text())


def verify_sam_source():
    manifest=asset_manifest()['sam_source']
    for relative, expected in manifest['files_sha256'].items():
        path=SAM_SOURCE/relative
        if not path.is_file() or path.is_symlink() or digest(path)!=expected:
            raise RuntimeError('SAM source missing or changed: '+relative+'; run python -m wecfu.setup_models')
    return manifest['commit']


def verify_tokenizer():
    for row in asset_manifest()['assets']:
        if row['path'].startswith('bert-tokenizer/'):
            path=MODEL_HOME/row['path']
            if not path.is_file() or digest(path)!=row['sha256']:
                raise RuntimeError('Tokenizer missing or changed: '+row['path'])


VERSIONS={'torch':'2.14.1', 'torchvision':'0.29.1', 'numpy':'2.5.4',
          'Pillow':'13.0.0', 'transformers':'4.57.6', 'tokenizers':'0.22.2'}
MODULE_DISTRIBUTIONS={'torch':'torch','torchvision':'torchvision','numpy':'numpy',
                      'PIL':'Pillow','transformers':'transformers','tokenizers':'tokenizers'}


def check_versions():
    if sys.version_info[:2] != (3,12):
        raise RuntimeError('The fixed model runtime requires Python 3.12')
    result={}
    for name, wanted in VERSIONS.items():
        actual=metadata.version(name)
        if actual.split('+',1)[0] != wanted:
            raise RuntimeError(f'{name}=={wanted} is required; installed {actual}')
        result[name]=actual
    return result


def verify_distribution_file(distribution, relative, expected=None):
    dist=metadata.distribution(distribution)
    if dist.version.split('+',1)[0] != VERSIONS[distribution]:
        raise RuntimeError('Runtime distribution version mismatch: '+distribution)
    matches=[item for item in dist.files or [] if str(item)==relative]
    if len(matches)!=1 or matches[0].hash is None or matches[0].hash.mode!='sha256':
        raise RuntimeError('Runtime file has no SHA256 RECORD entry: '+relative)
    item=matches[0];path=Path(dist.locate_file(item)).resolve()
    observed=digest(path)
    recorded=base64.urlsafe_b64encode(bytes.fromhex(observed)).rstrip(b'=').decode()
    if recorded!=item.hash.value or (expected is not None and observed!=expected):
        raise RuntimeError('Runtime source integrity mismatch: '+relative)
    return str(path), observed


def verify_module_file(module_name):
    module=sys.modules.get(module_name)
    if module is None or not getattr(module,'__file__',None):
        raise RuntimeError('Expected runtime module was not loaded: '+module_name)
    actual=Path(module.__file__).resolve()
    top=module_name.split('.')[0]
    if top in ('argparse','traceback'):
        # Standard-library objects remain explicitly checked by restricted_load.
        expected=Path(sysconfig.get_path('stdlib'))/(top+'.py')
        if actual!=expected.resolve(): raise RuntimeError('Standard-library module identity mismatch')
        return str(actual),digest(actual)
    distribution=MODULE_DISTRIBUTIONS.get(top)
    if distribution is None: raise RuntimeError('Unapproved runtime package: '+top)
    dist=metadata.distribution(distribution)
    relative=actual.relative_to(Path(dist.locate_file('')).resolve()).as_posix()
    return verify_distribution_file(distribution,relative)


def resolve_library_policy(policy):
    check_versions()
    return dict(verify_distribution_file(row['distribution'],row['path'],row.get('sha256'))
                for row in policy['source_files'])
