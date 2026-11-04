"""Ultra preparation contracts using synthetic files and mocked package/network work."""

import builtins
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tomllib
from types import SimpleNamespace
import urllib.error

import pytest

from wecfu import runtime_bootstrap as bootstrap
from wecfu import runtime_paths, setup_models


@pytest.fixture
def prepared(monkeypatch, tmp_path):
    for name in ('WECFU_MODEL_PYTHON', 'WECFU_CV_PYTHON', 'WECFU_SAM_DEVICE', 'WECFU_ENABLE_SAM2'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(bootstrap.sys, 'platform', 'darwin')
    monkeypatch.setattr(bootstrap.sys, 'version_info', (3, 12, 9))
    monkeypatch.setattr(bootstrap.platform, 'machine', lambda: 'synthetic')
    cache = tmp_path / 'cache'
    monkeypatch.setattr(runtime_paths, 'MODEL_HOME', cache)
    monkeypatch.setattr(runtime_paths, 'MODEL_PYTHON', tmp_path / 'original-python')
    monkeypatch.setattr(runtime_paths, 'CV_PYTHON', tmp_path / 'original-cv-python')
    monkeypatch.setattr(runtime_paths, 'SAM_DEVICE', 'cpu')
    events = []
    state = {'assets_ready': False}

    def check(cache_arg, **kwargs):
        assert cache_arg == cache
        events.append(('assets-check',))
        if not state['assets_ready']:
            raise RuntimeError('synthetic missing assets')
        return {'status': 'all_pinned_assets_verified'}

    def setup(cache_arg, **kwargs):
        assert cache_arg == cache
        events.append(('assets-setup',))
        state['assets_ready'] = True
        return {'status': 'all_pinned_assets_verified'}

    class Builder:
        def __init__(self, **kwargs):
            assert kwargs == {'with_pip': True, 'clear': False, 'symlinks': False}

        def create(self, folder):
            events.append(('venv', folder))
            (folder / 'bin').mkdir(parents=True)
            (folder / 'bin/python').write_text('synthetic interpreter, never executed')
            (folder / 'pyvenv.cfg').write_text('include-system-site-packages = false\n')

    def run(command, *, env, timeout=1200):
        events.append(('install', command, env.copy()))
        return ''

    def probe(python, cache_arg, *, env):
        assert cache_arg == cache
        events.append(('probe', Path(python), env.copy()))
        return {'versions': {}, 'device': 'cpu', 'python': str(python)}

    monkeypatch.setattr(setup_models, 'check', check)
    monkeypatch.setattr(setup_models, 'setup', setup)
    monkeypatch.setattr(bootstrap.venv, 'EnvBuilder', Builder)
    monkeypatch.setattr(bootstrap, '_run', run)
    monkeypatch.setattr(bootstrap, '_probe', probe)
    folder = cache / 'runtime' / f'sam-py312-darwin-synthetic-{bootstrap.RUNTIME_ID}'
    return SimpleNamespace(cache=cache, folder=folder, events=events, state=state)


def normalize_distribution(value):
    return re.sub(r'[-_.]+', '-', value).lower()


def test_bootstrap_requirements_match_model_extra():
    spec = tomllib.loads((Path(__file__).parents[1] / 'pyproject.toml').read_text())
    assert tuple(spec['project']['optional-dependencies']['models']) == bootstrap.REQUIREMENTS


@pytest.mark.parametrize('wrong_package', [None, *[value.split('==', 1)[0] for value in bootstrap.REQUIREMENTS]])
def test_probe_checks_every_pinned_package_using_synthetic_modules(monkeypatch, tmp_path, wrong_package):
    """Execute the actual generated probe, with fake modules instead of ML imports."""
    # Package binding is covered with real isolated subprocesses separately.
    monkeypatch.setattr(bootstrap, 'package_import_prelude', lambda: '')
    expected = {normalize_distribution(name): value for name, value in
                (item.split('==', 1) for item in bootstrap.REQUIREMENTS)}
    checked = []

    def version(name):
        key = normalize_distribution(name)
        checked.append(key)
        if wrong_package is not None and key == normalize_distribution(wrong_package):
            return '0.0.0'
        return expected[key] + ('+cpu' if key == 'torch' else '')

    def run(command, *, env, timeout):
        assert command[:3] == [str(tmp_path / 'python'), '-B', '-c']
        assert timeout == 90
        fake_sys = SimpleNamespace(path=[], platform='linux', executable=str(tmp_path / 'python'))
        imports = {
            'json': json, 'os': SimpleNamespace(environ=env), 'sys': fake_sys,
            'wecfu.runtime_paths': SimpleNamespace(check_versions=lambda: {}, verify_sam_source=lambda: None, SAM_SOURCE=tmp_path / 'source'),
            'wecfu.runtime_bootstrap': SimpleNamespace(REQUIREMENTS=bootstrap.REQUIREMENTS),
            'importlib.metadata': SimpleNamespace(version=version),
            'torch': SimpleNamespace(backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: False))),
            'sam2': SimpleNamespace(build_sam=object(), automatic_mask_generator=object()),
        }
        for name in ('torchvision', 'numpy', 'scipy', 'skimage', 'cv2', 'PIL', 'hydra', 'omegaconf', 'iopath'):
            imports[name] = SimpleNamespace()

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            assert name in imports, f'unexpected real dependency: {name}'
            return imports[name]

        namespace = {'__builtins__': {**vars(builtins), '__import__': fake_import}}
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            exec(command[-1], namespace)
        return out.getvalue()

    monkeypatch.setattr(bootstrap, '_run', run)
    if wrong_package is not None:
        with pytest.raises(RuntimeError, match=re.escape(wrong_package)):
            bootstrap._probe(tmp_path / 'python', tmp_path / 'cache', env={})
    else:
        result = bootstrap._probe(tmp_path / 'python', tmp_path / 'cache', env={})
        assert result['device'] == 'cpu'
        assert set(checked) == set(expected)


def test_first_setup_builds_isolated_runtime_and_second_start_reuses_it(prepared, monkeypatch):
    first = bootstrap.ensure_ultra()
    assert first['status'] == 'ready'
    assert Path(first['model_python']) == prepared.folder / 'bin/python'
    assert os.environ['WECFU_MODEL_PYTHON'] == first['model_python']
    assert os.environ['WECFU_CV_PYTHON'] == first['model_python']
    assert runtime_paths.MODEL_PYTHON == prepared.folder / 'bin/python'
    ready = prepared.folder / 'verified-runtime.json'
    assert json.loads(ready.read_text())['runtime_id'] == bootstrap.RUNTIME_ID
    assert [event[0] for event in prepared.events] == ['assets-check', 'assets-setup', 'venv', 'install', 'probe']
    initial_mtime = ready.stat().st_mtime_ns
    prepared.events.clear()
    # A genuinely new process has not inherited activation from the first one.
    monkeypatch.delenv('WECFU_MODEL_PYTHON')
    monkeypatch.delenv('WECFU_CV_PYTHON')
    assert bootstrap.ensure_ultra()['status'] == 'ready'
    assert [event[0] for event in prepared.events] == ['assets-check', 'probe']
    assert ready.stat().st_mtime_ns == initial_mtime


def test_external_model_and_cv_overrides_are_probed_without_installing(prepared, monkeypatch, tmp_path):
    prepared.state['assets_ready'] = True
    model = tmp_path / 'external-model'
    cv = tmp_path / 'external-cv'
    model.write_text('synthetic model interpreter')
    cv.write_text('synthetic cv interpreter')
    monkeypatch.setenv('WECFU_MODEL_PYTHON', str(model))
    monkeypatch.setenv('WECFU_CV_PYTHON', str(cv))
    result = bootstrap.ensure_ultra()
    assert result['status'] == 'ready'
    assert result['model_python'] == str(model)
    assert [event[0] for event in prepared.events] == ['assets-check', 'probe', 'probe']
    assert [event[1] for event in prepared.events if event[0] == 'probe'] == [model, cv]
    assert not prepared.folder.exists()
    assert model.read_text() == 'synthetic model interpreter'
    assert cv.read_text() == 'synthetic cv interpreter'


@pytest.mark.parametrize('raw_cv', ['~/wecfu-synthetic-cv-test', './synthetic-cv'])
def test_cv_override_uses_the_same_expanded_absolute_path_for_probe_and_activation(
    prepared, monkeypatch, tmp_path, raw_cv
):
    prepared.state['assets_ready'] = True
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('WECFU_MODEL_PYTHON', str(tmp_path / 'external-model'))
    monkeypatch.setenv('WECFU_CV_PYTHON', raw_cv)
    expected = Path(raw_cv).expanduser().absolute()
    assert bootstrap.ensure_ultra()['status'] == 'ready'
    probes = [event[1] for event in prepared.events if event[0] == 'probe']
    assert probes[-1] == expected
    assert runtime_paths.CV_PYTHON == expected
    assert os.environ['WECFU_CV_PYTHON'] == str(expected)


def test_bad_explicit_cv_override_does_not_activate_partial_runtime(prepared, monkeypatch, tmp_path):
    prepared.state['assets_ready'] = True
    cv = tmp_path / 'broken-cv'
    cv.write_text('synthetic broken interpreter')
    monkeypatch.setenv('WECFU_CV_PYTHON', str(cv))
    original_model = runtime_paths.MODEL_PYTHON
    original_cv = runtime_paths.CV_PYTHON
    original_probe = bootstrap._probe

    def probe(python, cache, *, env):
        if Path(python) == cv:
            raise RuntimeError('synthetic CV verification failure')
        return original_probe(python, cache, env=env)

    monkeypatch.setattr(bootstrap, '_probe', probe)
    with pytest.raises(RuntimeError, match='CV verification failure'):
        bootstrap.ensure_ultra()
    assert 'WECFU_MODEL_PYTHON' not in os.environ
    assert runtime_paths.MODEL_PYTHON == original_model
    assert runtime_paths.CV_PYTHON == original_cv
    assert os.environ['WECFU_CV_PYTHON'] == str(cv)


def test_preparation_network_failure_is_runtime_error_without_ready_receipt(prepared, monkeypatch):
    def offline(*args, **kwargs):
        raise urllib.error.URLError('synthetic offline')

    monkeypatch.setattr(setup_models, 'setup', offline)
    with pytest.raises(RuntimeError, match='synthetic offline'):
        bootstrap.ensure_ultra()
    assert 'WECFU_MODEL_PYTHON' not in os.environ
    assert not (prepared.folder / 'verified-runtime.json').exists()


def test_failed_install_or_probe_cannot_write_ready_receipt(prepared, monkeypatch):
    prepared.state['assets_ready'] = True
    monkeypatch.setattr(bootstrap, '_probe', lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError('bad pinned package')))
    with pytest.raises(RuntimeError, match='bad pinned package'):
        bootstrap.ensure_ultra()
    assert 'WECFU_MODEL_PYTHON' not in os.environ
    assert not (prepared.folder / 'verified-runtime.json').exists()


def test_changed_assets_are_preserved_and_prevent_activation(prepared, monkeypatch):
    bad_asset = prepared.cache / 'sam2/sam2.1_hiera_tiny.pt'
    bad_asset.parent.mkdir(parents=True)
    bad_asset.write_bytes(b'changed asset must not be replaced')

    def refuse(*args, **kwargs):
        raise RuntimeError('Existing asset differs')

    monkeypatch.setattr(setup_models, 'setup', refuse)
    with pytest.raises(RuntimeError, match='Existing asset differs'):
        bootstrap.ensure_ultra()
    assert bad_asset.read_bytes() == b'changed asset must not be replaced'
    assert 'WECFU_MODEL_PYTHON' not in os.environ
    assert not prepared.folder.exists()


def test_sam_profile_only_copies_pinned_sam_assets_and_refuses_changed_cache(monkeypatch, tmp_path):
    payload = b'synthetic fixed SAM weight bytes'
    source_code = b'# synthetic pinned source\n'
    manifest = {
        'assets': [
            {'path': 'sam2/test.pt', 'offline_path': 'sam2/test.pt',
             'bytes': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()},
            {'path': 'legacy-dino/model.pth', 'offline_path': 'absent-dino',
             'bytes': 1, 'sha256': '0' * 64},
        ],
        'sam_source': {'files_sha256': {'sam2/test.py': hashlib.sha256(source_code).hexdigest()},
                       'files_bytes': {'sam2/test.py': len(source_code)}},
    }
    package = tmp_path / 'package'
    package.mkdir()
    (package / 'model_assets.json').write_text(json.dumps(manifest))
    monkeypatch.setattr(runtime_paths, 'PACKAGE_ROOT', package)
    source = tmp_path / 'offline'
    (source / 'sam2/source/sam2').mkdir(parents=True)
    (source / 'sam2/test.pt').write_bytes(payload)
    (source / 'sam2/source/sam2/test.py').write_bytes(source_code)
    cache = tmp_path / 'cache'
    result = setup_models.setup(cache, source)
    assert result['profile'] == 'sam'
    assert result['verified_files'] == 2
    assert (cache / 'sam2/test.pt').read_bytes() == payload
    assert not (cache / 'legacy-dino').exists()
    changed = b'keep this changed asset for diagnosis'
    (cache / 'sam2/test.pt').write_bytes(changed)
    with pytest.raises(RuntimeError, match='Existing asset differs'):
        setup_models.setup(cache, source)
    assert (cache / 'sam2/test.pt').read_bytes() == changed


def test_pip_install_ignores_inherited_target_and_indexes(prepared, monkeypatch, tmp_path):
    monkeypatch.setenv('PIP_TARGET', str(tmp_path / 'outside-env'))
    monkeypatch.setenv('PIP_EXTRA_INDEX_URL', 'https://invalid.example.test/simple')
    monkeypatch.setenv('PIP_PREFIX', str(tmp_path / 'outside-prefix'))
    monkeypatch.setenv('PYTHONHOME', str(tmp_path / 'wrong-python-home'))
    assert bootstrap.ensure_ultra()['status'] == 'ready'
    installs = [event for event in prepared.events if event[0] == 'install']
    assert installs
    for _, command, env in installs:
        assert '--isolated' in command or not any(key in env for key in ('PIP_TARGET', 'PIP_PREFIX', 'PIP_EXTRA_INDEX_URL'))
        assert 'PYTHONHOME' not in env
        assert command[0] == str(prepared.folder / 'bin/python')
    assert not (tmp_path / 'outside-env').exists()
    assert not (tmp_path / 'outside-prefix').exists()


def test_auto_runtime_parent_symlink_is_rejected_before_writes(prepared, tmp_path):
    outside = tmp_path / 'outside'
    outside.mkdir()
    prepared.cache.mkdir()
    (prepared.cache / 'runtime').symlink_to(outside, target_is_directory=True)
    with pytest.raises(RuntimeError):
        bootstrap.ensure_ultra()
    assert list(outside.iterdir()) == []


def test_setup_lock_is_exclusive_and_released_after_exception(tmp_path):
    cache = tmp_path / 'cache'
    with pytest.raises(ValueError, match='synthetic interrupt'):
        with bootstrap._setup_lock(cache):
            with pytest.raises(RuntimeError, match='another WeCFU process'):
                with bootstrap._setup_lock(cache):
                    pytest.fail('second preparation acquired the same lock')
            raise ValueError('synthetic interrupt')
    with bootstrap._setup_lock(cache):
        assert cache.is_dir()


def test_probe_rejects_malformed_runtime_output(monkeypatch, tmp_path):
    monkeypatch.setattr(bootstrap, '_run', lambda *args, **kwargs: 'not runtime JSON')
    with pytest.raises(RuntimeError, match='invalid verification data'):
        bootstrap._probe(tmp_path / 'python', tmp_path / 'cache', env={})


@pytest.mark.parametrize('error', [OSError('synthetic exec failure'), subprocess.TimeoutExpired('synthetic command', 1)])
def test_runtime_subprocess_errors_are_normalized(monkeypatch, error):
    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(bootstrap.subprocess, 'run', fail)
    with pytest.raises(RuntimeError, match='could not finish'):
        bootstrap._run(['synthetic-interpreter'], env={}, timeout=1)


def test_disabled_model_does_not_prepare_anything(prepared, monkeypatch):
    monkeypatch.setenv('WECFU_ENABLE_SAM2', '0')
    assert bootstrap.ensure_ultra() == {'status': 'disabled'}
    assert prepared.events == []
    assert not prepared.cache.exists()


@pytest.mark.parametrize('receipt', ['broken json', '[]', 'null', '"string"', '42', '{}', '{"runtime_id":"old"}'])
def test_prepared_python_ignores_invalid_receipts_without_breaking_imports(prepared, receipt):
    (prepared.folder / 'bin').mkdir(parents=True)
    (prepared.folder / 'bin/python').write_text('synthetic interpreter')
    (prepared.folder / 'verified-runtime.json').write_text(receipt)
    assert bootstrap.prepared_python(prepared.cache) is None


def test_prepared_python_requires_real_interpreter_and_unlinked_receipt(prepared, tmp_path):
    prepared.folder.mkdir(parents=True)
    receipt = prepared.folder / 'verified-runtime.json'
    receipt.write_text(json.dumps({'runtime_id': bootstrap.RUNTIME_ID}))
    assert bootstrap.prepared_python(prepared.cache) is None
    (prepared.folder / 'bin').mkdir()
    python = prepared.folder / 'bin/python'
    python.write_text('synthetic interpreter')
    assert bootstrap.prepared_python(prepared.cache) == python
    receipt.unlink()
    outside = tmp_path / 'outside-receipt.json'
    outside.write_text(json.dumps({'runtime_id': bootstrap.RUNTIME_ID}))
    receipt.symlink_to(outside)
    assert bootstrap.prepared_python(prepared.cache) is None


def test_runtime_paths_discovers_prepared_runtime_but_preserves_explicit_overrides(prepared, monkeypatch, tmp_path):
    (prepared.folder / 'bin').mkdir(parents=True)
    python = prepared.folder / 'bin/python'
    python.write_text('synthetic interpreter')
    (prepared.folder / 'verified-runtime.json').write_text(json.dumps({'runtime_id': bootstrap.RUNTIME_ID}))
    monkeypatch.setenv('WECFU_MODEL_HOME', str(prepared.cache))

    def fresh_paths():
        spec = importlib.util.spec_from_file_location('wecfu._synthetic_runtime_paths', runtime_paths.__file__)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    detected = fresh_paths()
    assert detected.MODEL_PYTHON == detected.CV_PYTHON == python
    external = tmp_path / 'external-python'
    monkeypatch.setenv('WECFU_MODEL_PYTHON', str(external))
    assert fresh_paths().MODEL_PYTHON == external


def test_standalone_sam_runtime_check_requires_full_probe_even_with_ready_receipt(prepared, monkeypatch):
    calls = []

    def fail(python, cache, *, env):
        calls.append((python, cache, env))
        raise RuntimeError('synthetic pinned runtime mismatch')

    monkeypatch.setattr(bootstrap, '_probe', fail)
    monkeypatch.setenv('PYTHONHOME', '/synthetic/wrong-home')
    with pytest.raises(RuntimeError, match='pinned runtime mismatch'):
        setup_models.runtime_check(prepared.cache)
    assert len(calls) == 1
    assert calls[0][:2] == (runtime_paths.MODEL_PYTHON, prepared.cache)
    assert 'PYTHONHOME' not in calls[0][2]
    assert calls[0][2]['HF_HUB_OFFLINE'] == '1'
    assert calls[0][2]['PYTHONNOUSERSITE'] == '1'


def test_subprocess_uses_application_directory_instead_of_callers_working_directory(monkeypatch, tmp_path):
    seen = []

    def run(command, **kwargs):
        seen.append(kwargs)
        return SimpleNamespace(returncode=0, stdout='synthetic ok')

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(bootstrap.subprocess, 'run', run)
    assert bootstrap._run(['synthetic-python'], env={}) == 'synthetic ok'
    assert seen[0]['cwd'] == bootstrap.PACKAGE_ROOT
