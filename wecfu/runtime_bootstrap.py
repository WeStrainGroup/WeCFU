"""Prepare the pinned Ultra runtime at local startup, never during inference.

The model environment is isolated from Conda/application dependencies. Only
public packages and digest-pinned SAM assets are downloaded; photo workspaces
are neither read nor modified here.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import tarfile
import venv

# Keep the tested numeric/runtime versions identical to the model extra.
REQUIREMENTS = (
    'numpy==2.5.4', 'scipy==1.18.1', 'scikit-image==0.26.0',
    'opencv-python-headless==5.0.0.93', 'pillow==13.0.0',
    'torch==2.14.1', 'torchvision==0.29.1', 'transformers==4.57.6',
    'tokenizers==0.22.2', 'huggingface-hub==0.36.2', 'hydra-core==1.3.2',
    'omegaconf==2.3.1', 'iopath==0.1.10', 'tqdm==4.70.1', 'safetensors==0.8.0',
)
RUNTIME_ID = hashlib.sha256('\n'.join(REQUIREMENTS).encode()).hexdigest()[:16]
PACKAGE_ROOT = Path(__file__).resolve().parent


def runtime_directory(cache):
    return Path(cache)/'runtime'/f'sam-py312-{sys.platform}-{platform.machine()}-{RUNTIME_ID}'


def prepared_python(cache):
    folder = runtime_directory(cache)
    python = folder/'bin/python'
    receipt = folder/'verified-runtime.json'
    if folder.is_symlink() or python.is_symlink() or receipt.is_symlink():
        return None
    try:
        record = json.loads(receipt.read_text())
        valid = isinstance(record, dict) and record.get('runtime_id') == RUNTIME_ID
    except (OSError, ValueError):
        return None
    return python if valid and python.is_file() else None


def _run(command, *, env, timeout=1200):
    try:
        result = subprocess.run(command, cwd=PACKAGE_ROOT, env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f'Ultra preparation could not finish: {exc}') from exc
    if result.returncode:
        raise RuntimeError('Ultra preparation failed:\n' + result.stdout[-5000:])
    return result.stdout


def package_import_prelude():
    """Expose this package, without exposing the application's site-packages."""
    return f'''import importlib.util,sys
_wecfu_spec=importlib.util.spec_from_file_location("wecfu", {str(PACKAGE_ROOT / '__init__.py')!r}, submodule_search_locations=[{str(PACKAGE_ROOT)!r}])
_wecfu_module=importlib.util.module_from_spec(_wecfu_spec)
sys.modules["wecfu"]=_wecfu_module
_wecfu_spec.loader.exec_module(_wecfu_module)
'''


def isolated_environment(env):
    return {**{k:v for k,v in env.items() if k not in ('PYTHONHOME', 'PYTHONPATH')},
            'PYTHONPATH':'', 'PYTHONNOUSERSITE':'1', 'PYTHONDONTWRITEBYTECODE':'1'}


def _probe(python, cache, *, env):
    """Verify real imports, pinned versions, source and device in the target env."""
    code = package_import_prelude() + """import json,os,sys
from wecfu.runtime_paths import check_versions,verify_sam_source,SAM_SOURCE
from wecfu.runtime_bootstrap import REQUIREMENTS
from importlib.metadata import version
versions=check_versions();verify_sam_source()
for requirement in REQUIREMENTS:
 name,wanted=requirement.split("==");actual=version(name).split("+",1)[0]
 if actual!=wanted:raise RuntimeError(name+" must be "+wanted+"; found "+actual)
import torch,torchvision,numpy,scipy,skimage,cv2,PIL,hydra,omegaconf,iopath
sys.path.insert(0,str(SAM_SOURCE))
from sam2 import build_sam,automatic_mask_generator
requested=os.environ.get('WECFU_SAM_DEVICE')
device=requested or ('mps' if sys.platform=='darwin' and torch.backends.mps.is_available() else 'cpu')
if device not in ('cpu','mps') or (device=='mps' and not torch.backends.mps.is_available()):raise RuntimeError('Requested SAM device is unavailable')
print(json.dumps({'versions':versions,'device':device,'python':sys.executable}))
"""
    output = _run([str(python), '-B', '-c', code],
                  env={**isolated_environment(env), 'WECFU_MODEL_HOME':str(cache)}, timeout=90)
    try:
        return json.loads(output.strip().splitlines()[-1])
    except (ValueError, IndexError) as exc:
        raise RuntimeError('Ultra runtime returned invalid verification data') from exc


@contextlib.contextmanager
def _setup_lock(cache):
    # flock releases on interruption/crash; no stale lock file can block startup.
    import fcntl
    cache.mkdir(parents=True, exist_ok=True)
    with (cache/'.ultra-setup.lock').open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('Ultra is being prepared by another WeCFU process. Retry after it finishes.') from exc
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def _activate(python, device):
    os.environ['WECFU_MODEL_PYTHON'] = str(python)
    os.environ.setdefault('WECFU_CV_PYTHON', str(python))
    os.environ['WECFU_SAM_DEVICE'] = device
    # runtime_paths is imported for model_home/setup; refresh its configured
    # paths before server/provider modules capture those values.
    from . import runtime_paths
    runtime_paths.MODEL_PYTHON = Path(python)
    runtime_paths.CV_PYTHON = Path(os.environ['WECFU_CV_PYTHON'])
    runtime_paths.SAM_DEVICE = device


def _ensure_ultra():
    if sys.platform not in ('darwin', 'linux'):
        raise RuntimeError('Ultra currently supports macOS and Linux. Use Lite or Custom on this system.')
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError('Ultra setup requires Python 3.12. Install the current Conda package in a Python 3.12 environment.')
    if os.environ.get('WECFU_ENABLE_SAM2', '1') == '0':
        return {'status':'disabled'}
    from . import runtime_paths, setup_models
    cache = runtime_paths.MODEL_HOME
    env = isolated_environment(os.environ)
    external = os.environ.get('WECFU_MODEL_PYTHON')
    folder = runtime_directory(cache)
    python = Path(external).expanduser().absolute() if external else folder/'bin/python'
    for managed in (cache/'sam2', cache/'runtime', folder, folder/'bin', python if not external else folder):
        if managed.is_symlink():
            raise RuntimeError('Ultra setup will not write through a managed symlink: '+str(managed))
    if (cache/'sam2').is_dir() and any(p.is_symlink() for p in (cache/'sam2').rglob('*')):
        raise RuntimeError('Ultra assets contain a symlink; setup did not replace it.')
    with _setup_lock(cache):
        # Verify before downloads on repeat starts; changed cached assets fail
        # rather than silently replacing files.
        try:
            setup_models.check(cache)
            assets_ready = True
        except RuntimeError:
            assets_ready = False
        if not assets_ready:
            print('Preparing Ultra: downloading and verifying SAM assets (first start only)...', flush=True)
            setup_models.setup(cache)
        if external:
            proof = _probe(python, cache, env=env)
        else:
            ready = folder/'verified-runtime.json'
            proof = None
            if ready.is_file() and python.is_file():
                proof = _probe(python, cache, env=env)
            if proof is None:
                print('Preparing Ultra: installing its isolated runtime (first start only)...', flush=True)
                if not (folder/'pyvenv.cfg').is_file():
                    venv.EnvBuilder(with_pip=True, clear=False, symlinks=False).create(folder)
                install_env = {**{k:v for k,v in env.items() if not k.startswith('PIP_')}, 'PIP_CONFIG_FILE':os.devnull, 'PIP_DISABLE_PIP_VERSION_CHECK':'1'}
                base = [str(python), '-m', 'pip', '--isolated', 'install', '--index-url', 'https://pypi.org/simple']
                if sys.platform == 'linux':
                    _run([str(python), '-m', 'pip', '--isolated', 'install', '--index-url',
                          'https://download.pytorch.org/whl/cpu', 'torch==2.14.1', 'torchvision==0.29.1'], env=install_env)
                _run(base + list(REQUIREMENTS), env=install_env)
                proof = _probe(python, cache, env=env)
                temporary = folder/'verified-runtime.tmp'
                temporary.write_text(json.dumps({'runtime_id':RUNTIME_ID,'verified_at':time.time(),**proof},indent=2)+'\n')
                os.replace(temporary, ready)
        # Activate only after all configured interpreters have passed.
        cv_python = Path(os.environ.get('WECFU_CV_PYTHON', str(python))).expanduser().absolute()
        if cv_python != python:
            _probe(cv_python, cache, env=env)
        os.environ['WECFU_CV_PYTHON'] = str(cv_python)
        _activate(python, proof['device'])
    print('Ultra is ready.', flush=True)
    return {'status':'ready','runtime_id':RUNTIME_ID,'model_python':str(python),'device':proof['device']}


def ensure_ultra():
    try:
        return _ensure_ultra()
    except RuntimeError:
        raise
    except (OSError, ValueError, subprocess.SubprocessError, tarfile.TarError) as exc:
        raise RuntimeError(f'Ultra preparation could not finish: {exc}') from exc
