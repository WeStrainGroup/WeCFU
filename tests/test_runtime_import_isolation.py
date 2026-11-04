"""Reproduce installed-app dependency shadowing with tiny fake packages only.

The subprocess interpreter is a fresh standard-library venv without pip. No
network, model weights, real ML packages or photographs are used.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import venv

import pytest

from wecfu import runtime_bootstrap as bootstrap


@pytest.fixture(scope='module')
def installed_layout(tmp_path_factory):
    root = tmp_path_factory.mktemp('installed-runtime-isolation')
    environment = root / 'model-environment'
    venv.EnvBuilder(with_pip=False, symlinks=False).create(environment)
    python = environment / 'bin/python'
    clean_env = {key: value for key, value in os.environ.items() if key not in ('PYTHONHOME', 'PYTHONPATH')}
    query = subprocess.run([str(python), '-c', 'import sysconfig; print(sysconfig.get_path("purelib"))'],
                           env=clean_env, cwd=root, capture_output=True, text=True, check=True, timeout=15)
    model_site = Path(query.stdout.strip())
    host_site = root / 'host-conda-site-packages'
    package = host_site / 'wecfu'
    (package / 'server').mkdir(parents=True)
    # An installed app can import dependencies, but must see the worker's copy.
    (package / '__init__.py').write_text(
        'import numpy\nassert numpy.ORIGIN == "model", "host dependency leaked into app import"\n')
    (package / 'server/__init__.py').write_text('')
    shutil.copyfile(bootstrap.__file__, package / 'runtime_bootstrap.py')
    (package / 'runtime_paths.py').write_text('''from pathlib import Path
import os
from importlib.metadata import version
SAM_SOURCE=Path(os.environ['WECFU_MODEL_HOME'])/'source'
def verify_sam_source(): return 'synthetic-source'
def check_versions(): return {name:version(name) for name in ('numpy','opencv-python-headless')}
''')

    for requirement in bootstrap.REQUIREMENTS:
        name, version = requirement.split('==')
        metadata = model_site / f'{name.replace("-", "_")}-{version}.dist-info'
        metadata.mkdir()
        (metadata / 'METADATA').write_text(f'Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n')
    for name in ('numpy', 'torchvision', 'scipy', 'skimage', 'cv2', 'PIL', 'hydra', 'omegaconf', 'iopath'):
        (model_site / f'{name}.py').write_text('ORIGIN="model"\n')
    (model_site / 'torch.py').write_text(
        'from types import SimpleNamespace\nbackends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda:False))\n')

    # These reproduce the incompatible Conda distributions that used to win.
    for name in ('numpy', 'cv2'):
        (host_site / f'{name}.py').write_text(f'raise RuntimeError("host {name} must never be imported")\n')
    metadata = host_site / 'opencv_python_headless-5.0.0.dist-info'
    metadata.mkdir()
    (metadata / 'METADATA').write_text('Metadata-Version: 2.1\nName: opencv-python-headless\nVersion: 5.0.0\n')
    injected = root / 'inherited-pythonpath'
    (injected / 'wecfu').mkdir(parents=True)
    (injected / 'wecfu/__init__.py').write_text('raise RuntimeError("inherited wecfu shadow loaded")\n')
    (injected / 'numpy.py').write_text('raise RuntimeError("inherited numpy shadow loaded")\n')

    cache = root / 'cache'
    (cache / 'source/sam2').mkdir(parents=True)
    (cache / 'source/sam2/__init__.py').write_text('build_sam=None\nautomatic_mask_generator=None\n')
    worker = package / 'server/sam_worker.py'
    shutil.copyfile(Path(bootstrap.__file__).parent / 'server/sam_worker.py', worker)
    # The actual worker imports these constants before reading any request. The
    # stub records dependency origins; EOF then closes the worker without work.
    (package / 'server/sam_runtime.py').write_text('''import json,os
from pathlib import Path
import numpy,cv2
Path(os.environ['WECFU_TEST_IMPORT_RECORD']).write_text(json.dumps({'numpy':numpy.__file__,'cv2':cv2.__file__}))
CHECKPOINT=SOURCE=Path('.')
COMPONENT_PARAMS=MODEL_SETTINGS={}
ENGINE=RECIPE_ID=MODEL_SHA256='synthetic'
PLATE_INSET=.95
RSS_LIMIT_BYTES=MAX_JSON_BYTES=1024
SAM_DEVICE='cpu'
''')
    return dict(root=root, python=python, model_site=model_site, host_site=host_site,
                package=package, injected=injected, cache=cache, worker=worker)


def contaminated_environment(layout):
    return {**os.environ, 'PYTHONPATH':str(layout['injected']),
            'PYTHONHOME':str(layout['root'] / 'nonexistent-python-home'),
            'WECFU_SAM_DEVICE':'cpu'}


def test_actual_probe_loads_only_model_dependencies_beside_installed_app(installed_layout, monkeypatch):
    layout = installed_layout
    monkeypatch.setattr(bootstrap, 'PACKAGE_ROOT', layout['package'])
    monkeypatch.chdir(layout['host_site'])
    result = bootstrap._probe(layout['python'], layout['cache'], env=contaminated_environment(layout))
    assert result['device'] == 'cpu'
    assert result['versions']['opencv-python-headless'] == '5.0.0.93'
    assert result['versions']['numpy'] == '2.5.4'
    assert result['python'] == str(layout['python'])


@pytest.mark.parametrize('mode', ['cv', 'infer'])
def test_actual_worker_binds_app_without_exposing_host_site_packages(installed_layout, mode):
    layout = installed_layout
    record = layout['root'] / f'{mode}-imports.json'
    env = {**bootstrap.isolated_environment(contaminated_environment(layout)),
           'WECFU_TEST_IMPORT_RECORD':str(record)}
    assert env['PYTHONPATH'] == '' and 'PYTHONHOME' not in env
    result = subprocess.run([str(layout['python']), str(layout['worker']), '--serve', mode],
                            env=env, cwd=layout['host_site'], stdin=subprocess.DEVNULL,
                            capture_output=True, text=True, timeout=15, check=False)
    assert result.returncode == 0, result.stderr
    origins = json.loads(record.read_text())
    assert origins == {'numpy':str(layout['model_site'] / 'numpy.py'),
                       'cv2':str(layout['model_site'] / 'cv2.py')}
