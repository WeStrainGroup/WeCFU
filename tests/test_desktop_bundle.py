"""Synthetic desktop-payload contracts; no download, pip, model or real photo."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys

import pytest


SPEC = importlib.util.spec_from_file_location('desktop_resource_builder',
    Path(__file__).parents[1] / 'tools/build_desktop_resources.py')
build = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build)
TARGET = 'darwin-arm64'


@pytest.fixture
def source(monkeypatch, tmp_path):
    repo = tmp_path / 'source'
    (repo / 'wecfu/__pycache__').mkdir(parents=True)
    (repo / 'wecfu/__init__.py').write_text('new public source\n')
    (repo / 'wecfu/__pycache__/omit.pyc').write_bytes(b'not copied')
    (repo / 'LICENSES').mkdir()
    (repo / 'LICENSES/Third.txt').write_text('new public license')
    for name in ('LICENSE', 'NOTICE', 'THIRD_PARTY_NOTICES.md'):
        (repo / name).write_text(name)
    (repo / 'pyproject.toml').write_text(
        '[project]\nversion="1.2.3"\n[project.optional-dependencies]\nmodels=["numpy==2"]\n')
    monkeypatch.setattr(build, 'REPO', repo)
    monkeypatch.setattr(build, 'APP_REQUIREMENTS', ('fastapi==1',))
    monkeypatch.setattr(build, 'target', lambda: TARGET)
    def git(command, **kwargs):
        if command == ['git', 'rev-parse', 'HEAD']:
            return 'f' * 40 + '\n'
        if command == ['git', 'status', '--porcelain', '--untracked-files=normal']:
            return ' M wecfu/__init__.py\n'
        raise AssertionError('Unexpected external command: ' + repr(command))
    monkeypatch.setattr(build.subprocess, 'check_output', git)
    monkeypatch.setattr(build.subprocess, 'run', lambda *a, **k: pytest.fail('Synthetic contract launched a command'))
    monkeypatch.setattr(build.urllib.request, 'urlretrieve', lambda *a, **k: pytest.fail('Contract made a download'))
    return repo


@pytest.fixture
def payload(source, tmp_path):
    root = tmp_path / 'payload'
    data = {
        build.RUNTIMES[TARGET]['python']: b'portable interpreter placeholder',
        'app/desktop_entry.py': b'old entry point',
        'app/wecfu/__init__.py': b'old public source',
        'models/sam2/weights.bin': b'synthetic fixed model bytes',
        'models/bundle-manifest.json': b'nested manifest is an ordinary resource',
        'licenses/installed-distributions.txt': b'fastapi==1\nnumpy==2\n',
        'licenses/old-notice.txt': b'old license',
    }
    for name, value in data.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
    record = dict(schema_version=1, app_version='1.2.2', platform=TARGET,
        python=build.RUNTIMES[TARGET]['python'], entrypoint='app/desktop_entry.py', models='models',
        runtime_archive_sha256=build.RUNTIMES[TARGET]['sha256'],
        files={name: hashlib.sha256(value).hexdigest() for name, value in data.items()})
    (root / 'bundle-manifest.json').write_text(json.dumps(record))
    return root


def invoke(monkeypatch, root, *, refresh=True):
    command = ['build_desktop_resources', '--output', str(root)]
    if refresh:
        command.append('--refresh-app')
    monkeypatch.setattr(sys, 'argv', command)
    build.main()


def test_new_build_refuses_existing_data_before_download_or_replacement(source, tmp_path, monkeypatch):
    root = tmp_path / 'not-owned'
    (root / 'app').mkdir(parents=True)
    marker = root / 'app/keep.txt'
    marker.write_text('user data')
    with pytest.raises(RuntimeError, match='empty output'):
        invoke(monkeypatch, root, refresh=False)
    assert marker.read_text() == 'user data' and not (root / 'runtime').exists()


def test_new_build_accepts_only_empty_or_empty_git_placeholder(source, tmp_path):
    empty = tmp_path / 'empty'
    empty.mkdir()
    (empty / '.gitkeep').write_bytes(b'')
    assert build.prepare_output(empty, TARGET, refresh=False) == empty
    (empty / '.gitkeep').write_bytes(b'data')
    with pytest.raises(RuntimeError, match='empty output'):
        build.prepare_output(empty, TARGET, refresh=False)


def test_refresh_requires_completed_manifest_before_deleting_app(payload, monkeypatch):
    (payload / 'bundle-manifest.json').unlink()
    before = (payload / 'app/desktop_entry.py').read_bytes()
    with pytest.raises(RuntimeError, match='completed bundle manifest'):
        invoke(monkeypatch, payload)
    assert (payload / 'app/desktop_entry.py').read_bytes() == before


@pytest.mark.parametrize('mutation,match', [
    ('runtime', 'resource changed'), ('model', 'resource changed'), ('missing', 'missing or unexpected files'),
    ('extra', 'missing or unexpected files'), ('cache', 'missing or unexpected files'),
    ('empty-directory', 'missing or unexpected directories'),
])
def test_refresh_refuses_changed_or_unrecorded_items_without_staging(payload, monkeypatch, mutation, match):
    if mutation == 'runtime':
        (payload / build.RUNTIMES[TARGET]['python']).write_bytes(b'changed interpreter')
    elif mutation == 'model':
        (payload / 'models/sam2/weights.bin').write_bytes(b'changed model')
    elif mutation == 'missing':
        (payload / 'models/sam2/weights.bin').unlink()
    elif mutation == 'extra':
        (payload / 'unrecorded.txt').write_text('do not absorb into a new manifest')
    elif mutation == 'cache':
        (payload / 'runtime/__pycache__').mkdir()
        (payload / 'runtime/__pycache__/unrecorded.pyc').write_bytes(b'executable unsealed cache')
    else:
        (payload / 'unrecorded-empty').mkdir()
    before = (payload / 'app/desktop_entry.py').read_bytes()
    with pytest.raises(RuntimeError, match=match):
        invoke(monkeypatch, payload)
    assert (payload / 'app/desktop_entry.py').read_bytes() == before


def symlink_or_skip(link, destination):
    try:
        link.symlink_to(destination, target_is_directory=True)
    except OSError:
        pytest.skip('This test account cannot create directory symlinks')


def test_refresh_rejects_root_alias(payload, monkeypatch, tmp_path):
    alias = tmp_path / 'alias'
    symlink_or_skip(alias, payload)
    with pytest.raises(RuntimeError, match='must not be a link'):
        invoke(monkeypatch, alias)
    assert (payload / 'app/desktop_entry.py').read_bytes() == b'old entry point'


def test_license_link_cannot_write_outside_payload(payload, monkeypatch, tmp_path):
    external = tmp_path / 'outside-licenses'
    shutil.move(payload / 'licenses', external)
    symlink_or_skip(payload / 'licenses', external)
    before = {p.name: p.read_bytes() for p in external.iterdir()}
    with pytest.raises(RuntimeError, match='linked resource'):
        invoke(monkeypatch, payload)
    assert {p.name: p.read_bytes() for p in external.iterdir()} == before


@pytest.mark.parametrize('field,value', [
    ('platform', 'win32-x64'), ('python', '../outside'), ('entrypoint', 'app/other.py'),
    ('runtime_archive_sha256', '0' * 64), ('schema_version', True), ('models', '/outside'),
])
def test_refresh_manifest_identity_is_checked_before_staging(payload, monkeypatch, field, value):
    path = payload / 'bundle-manifest.json'
    record = json.loads(path.read_text())
    record[field] = value
    path.write_text(json.dumps(record))
    with pytest.raises(RuntimeError, match='does not describe'):
        invoke(monkeypatch, payload)
    assert (payload / 'app/desktop_entry.py').read_bytes() == b'old entry point'


def test_duplicate_manifest_keys_fail_closed(payload, monkeypatch):
    (payload / 'bundle-manifest.json').write_text('{"schema_version":1,"schema_version":1}')
    with pytest.raises(RuntimeError, match='duplicate key'):
        invoke(monkeypatch, payload)


def test_refresh_cannot_keep_runtime_that_does_not_meet_new_source_pins(payload, monkeypatch):
    monkeypatch.setattr(build, 'APP_REQUIREMENTS', ('fastapi==999',))
    with pytest.raises(RuntimeError, match='rebuild instead of refreshing'):
        invoke(monkeypatch, payload)
    assert (payload / 'app/desktop_entry.py').read_bytes() == b'old entry point'


def test_valid_refresh_preserves_runtime_models_and_freeze_records_dirty_source(payload, source, monkeypatch):
    names = [build.RUNTIMES[TARGET]['python'], 'models/sam2/weights.bin',
             'models/bundle-manifest.json', 'licenses/installed-distributions.txt']
    before = {name: (payload / name).read_bytes() for name in names}
    invoke(monkeypatch, payload)
    assert {name: (payload / name).read_bytes() for name in names} == before
    assert (payload / 'app/wecfu/__init__.py').read_text() == 'new public source\n'
    assert not (payload / 'app/wecfu/__pycache__').exists()
    assert not (payload / 'licenses/old-notice.txt').exists()
    record = json.loads((payload / 'bundle-manifest.json').read_text())
    assert record['source_dirty'] is True and record['source_revision'] == 'f' * 40
    assert record['source_project_version'] == '1.2.3'
    assert record['app_requirements'] == ['fastapi==1']
    assert record['model_requirements'] == ['numpy==2']
    assert record['installed_distributions'] == 'licenses/installed-distributions.txt'
    assert record['build_tool_sha256'] == hashlib.sha256(Path(build.__file__).read_bytes()).hexdigest()
    assert 'bundle-manifest.json' not in record['files']
    assert 'models/bundle-manifest.json' in record['files']
    for name, checksum in record['files'].items():
        assert hashlib.sha256((payload / name).read_bytes()).hexdigest() == checksum
    assert not list(payload.glob('.app-stage-*'))
    build.validate_refresh(payload, TARGET)


def test_seal_records_all_bytecode_and_nested_manifests(payload):
    path = payload / 'runtime/__pycache__/fixture.pyc'
    path.parent.mkdir()
    path.write_bytes(b'test-only cache')
    build.seal(payload, TARGET, '1.2.3')
    record = json.loads((payload / 'bundle-manifest.json').read_text())
    assert 'runtime/__pycache__/fixture.pyc' in record['files']
    assert 'models/bundle-manifest.json' in record['files']
    build.validate_refresh(payload, TARGET)


def test_internal_file_link_materialized_but_external_link_refused(payload, tmp_path):
    link = payload / 'runtime/python-alias'
    try:
        link.symlink_to(payload / build.RUNTIMES[TARGET]['python'])
    except OSError:
        pytest.skip('This test account cannot create symlinks')
    build.seal(payload, TARGET, '1.2.3')
    assert link.is_file() and not link.is_symlink()
    outside = tmp_path / 'outside-data'
    outside.write_bytes(b'not a bundle resource')
    escape = payload / 'runtime/escape'
    escape.symlink_to(outside)
    with pytest.raises(RuntimeError, match='linked resource'):
        build.seal(payload, TARGET, '1.2.3')
    assert outside.read_bytes() == b'not a bundle resource' and escape.is_symlink()
