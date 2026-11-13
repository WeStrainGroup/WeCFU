"""Build a relocatable, offline desktop payload from digest-pinned CPython.

Run on each target OS. This build-only tool downloads public dependencies; the
delivered application never runs pip, Conda, venv creation or asset downloads.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import urllib.request

REPO = Path(__file__).resolve().parents[1]
RUNTIMES = {
    'darwin-arm64': {
        'file': 'cpython-3.12.16%2B20261026-aarch64-apple-darwin-install_only.tar.gz',
        'sha256': 'fbf4afef53c2a6b72bb741bc06d5671a9dfaf87bd84e5aa73ac9b3d0d589f14e',
        'python': 'runtime/bin/python3',
    },
    'win32-x64': {
        'file': 'cpython-3.12.16%2B20261026-x86_64-pc-windows-msvc-install_only.tar.gz',
        'sha256': '590dfcbe3a34c07301e6332e13e2188b98655cd072b08afa45a7998dc4c22bc5',
        'python': 'runtime/python.exe',
    },
}
APP_REQUIREMENTS = ('fastapi==0.162.0', 'pydantic==2.14.2', 'uvicorn==0.54.0',
                    'python-multipart==0.0.33', 'pandas==3.1.0')
MAX_MANIFEST_BYTES = 64 * 1024**2
MAX_BUNDLE_ENTRIES = 100_000


def is_link(path):
    return path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction())


def relative_path(value):
    reserved = {'CON', 'PRN', 'AUX', 'NUL', *('COM' + str(i) for i in range(1, 10)),
                *('LPT' + str(i) for i in range(1, 10))}
    if (not isinstance(value, str) or not value or '\\' in value or ':' in value
            or PurePosixPath(value).is_absolute()
            or any(ord(c) < 32 or ord(c) == 127 for c in value)
            or any(p in ('', '.', '..') or p.endswith((' ', '.'))
                   or p.split('.')[0].upper() in reserved for p in value.split('/'))):
        raise RuntimeError('Invalid bundle resource path')
    return value


def entries(root, *, allow_internal_file_links=False):
    """Do not follow directory links/junctions while inspecting a build root."""
    if is_link(root) or not root.is_dir():
        raise RuntimeError('Build output must be a regular directory, not a link')
    todo, count = [root], 0
    while todo:
        for path in sorted(todo.pop().iterdir()):
            count += 1
            if count > MAX_BUNDLE_ENTRIES:
                raise RuntimeError('Bundle contains too many filesystem entries')
            relative_path(path.relative_to(root).as_posix())
            if is_link(path):
                resolved = path.resolve(strict=True)
                if (not allow_internal_file_links or not resolved.is_relative_to(root.resolve())
                        or not resolved.is_file()):
                    raise RuntimeError('Bundle contains a linked resource: ' + str(path.relative_to(root)))
            elif path.is_dir():
                todo.append(path)
            elif not path.is_file():
                raise RuntimeError('Bundle contains a non-regular resource')
            yield path


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RuntimeError('Bundle manifest contains a duplicate key')
        result[key] = value
    return result


def project_metadata():
    return tomllib.loads((REPO / 'pyproject.toml').read_text())['project']


def verify_installed_versions(output):
    path = output / 'licenses/installed-distributions.txt'
    if not path.is_file() or is_link(path) or path.stat().st_size > 1024**2:
        raise RuntimeError('Bundle dependency inventory is missing or invalid')
    installed = {}
    for row in path.read_text(encoding='utf-8').splitlines():
        if '==' not in row or row.lstrip().startswith('#'):
            continue
        package, version = row.strip().split('==', 1)
        package = re.sub(r'[-_.]+', '-', package).lower()
        if package in installed:
            raise RuntimeError('Duplicate package in bundle dependency inventory')
        installed[package] = version
    requirements = [*APP_REQUIREMENTS, *project_metadata()['optional-dependencies']['models']]
    for requirement in requirements:
        package, wanted = requirement.split('==')
        actual = installed.get(re.sub(r'[-_.]+', '-', package).lower(), '')
        if actual.split('+', 1)[0] != wanted:
            raise RuntimeError('Bundled dependencies do not match this source; rebuild instead of refreshing: ' + package)


def validate_refresh(output, name):
    """A refresh may replace only an intact payload produced by this builder."""
    manifest_path = output / 'bundle-manifest.json'
    if (is_link(manifest_path) or not manifest_path.is_file()
            or manifest_path.stat().st_size > MAX_MANIFEST_BYTES):
        raise RuntimeError('Refresh requires a completed bundle manifest')
    try:
        record = json.loads(manifest_path.read_text(encoding='utf-8'), object_pairs_hook=_unique_object)
    except (ValueError, UnicodeError) as exc:
        raise RuntimeError('Refresh manifest is invalid') from exc
    if (type(record) is not dict or type(record.get('schema_version')) is not int
            or record['schema_version'] != 1 or record.get('platform') != name
            or record.get('python') != RUNTIMES[name]['python']
            or record.get('runtime_archive_sha256') != RUNTIMES[name]['sha256']
            or record.get('entrypoint') != 'app/desktop_entry.py'
            or record.get('models') != 'models'
            or not isinstance(record.get('app_version'), str) or not record['app_version']):
        raise RuntimeError('Refresh manifest does not describe this build target')
    files = record.get('files')
    if type(files) is not dict or not 1 <= len(files) <= MAX_BUNDLE_ENTRIES:
        raise RuntimeError('Refresh manifest has no valid file inventory')
    for path, checksum in files.items():
        relative_path(path)
        if path == 'bundle-manifest.json' or not isinstance(checksum, str) or not re.fullmatch('[a-f0-9]{64}', checksum):
            raise RuntimeError('Refresh manifest has an invalid file checksum')
    required = {RUNTIMES[name]['python'], 'app/desktop_entry.py', 'licenses/installed-distributions.txt'}
    if not required.issubset(files) or not any(path.startswith('models/') for path in files):
        raise RuntimeError('Refresh manifest is missing runtime, application or model resources')
    actual_entries = list(entries(output))
    actual_files = {p.relative_to(output).as_posix(): p for p in actual_entries
                    if p.is_file() and p != manifest_path}
    if set(actual_files) != set(files):
        raise RuntimeError('Refresh refused: bundle has missing or unexpected files')
    # New manifests also inventory empty directories. Legacy manifests may
    # contain only directory ancestors of their recorded regular files.
    expected_dirs = {parent.as_posix() for path in files for parent in PurePosixPath(path).parents
                     if parent != PurePosixPath('.')}
    if 'directories' in record:
        directories = record['directories']
        if not isinstance(directories, list) or any(not isinstance(p, str) for p in directories):
            raise RuntimeError('Refresh manifest has an invalid directory inventory')
        if len(set(directories)) != len(directories):
            raise RuntimeError('Refresh manifest has duplicate directories')
        for path in directories:
            relative_path(path)
        if not expected_dirs.issubset(directories):
            raise RuntimeError('Refresh manifest omits parent directories')
        expected_dirs = set(directories)
    if {p.relative_to(output).as_posix() for p in actual_entries if p.is_dir()} != expected_dirs:
        raise RuntimeError('Refresh refused: bundle has missing or unexpected directories')
    for path, checksum in files.items():
        if digest(actual_files[path]) != checksum:
            raise RuntimeError('Refresh refused: bundled resource changed: ' + path)
    verify_installed_versions(output)
    return record


def prepare_output(path, name, *, refresh):
    output = path.expanduser().absolute()
    if is_link(output):
        raise RuntimeError('Build output must not be a link')
    if output.exists() and not output.is_dir():
        raise RuntimeError('Build output must be a directory')
    if refresh:
        if not output.is_dir():
            raise RuntimeError('Refresh requires a completed payload')
        validate_refresh(output, name)
    elif output.exists():
        remaining = list(output.iterdir())
        if any(p.name != '.gitkeep' or is_link(p) or not p.is_file() or p.stat().st_size
               for p in remaining):
            raise RuntimeError('New builds require an empty output directory; existing data was not changed')
    output.mkdir(parents=True, exist_ok=True)
    return output.resolve()


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def target():
    machine = platform.machine().lower()
    arch = 'arm64' if machine in ('aarch64', 'arm64') else 'x64' if machine in ('amd64', 'x86_64') else machine
    name = f'{sys.platform}-{arch}'
    if name not in RUNTIMES:
        raise RuntimeError(f'Unvalidated desktop build target: {name}')
    return name


def clean_env():
    return {**{k: v for k, v in os.environ.items() if not k.startswith(('PYTHON', 'WECFU_', 'PIP_'))},
            'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONNOUSERSITE': '1',
            'PIP_CONFIG_FILE': os.devnull, 'PIP_DISABLE_PIP_VERSION_CHECK': '1'}


def stage_app(output, *, refresh=False):
    # Check every destination before writing, even when called outside main().
    for path in (output, output / 'app', output / 'licenses'):
        if is_link(path):
            raise RuntimeError('Application staging refuses linked directories')
    if not refresh and any((output / name).exists() for name in ('app', 'licenses')):
        raise RuntimeError('Application staging will not replace an existing directory')
    for folder in (output / 'app', output / 'licenses'):
        if folder.exists():
            list(entries(folder))
    list(entries(REPO / 'wecfu'))
    list(entries(REPO / 'LICENSES'))
    freeze = output / 'licenses/installed-distributions.txt'
    freeze_bytes = freeze.read_bytes() if refresh and freeze.is_file() else None
    # Build replacements fully before removing the already-validated old trees.
    with tempfile.TemporaryDirectory(prefix='.app-stage-', dir=output) as staging:
        staging = Path(staging)
        app, licenses = staging / 'app', staging / 'licenses'
        app.mkdir(); licenses.mkdir()
        shutil.copytree(REPO / 'wecfu', app / 'wecfu',
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo'))
        (app / 'desktop_entry.py').write_text(
            'import sys\nfrom pathlib import Path\n'
            'sys.path.insert(0, str(Path(__file__).resolve().parent))\n'
            'from wecfu.desktop_host import main\nraise SystemExit(main())\n', encoding='utf-8')
        for name in ('LICENSE', 'NOTICE', 'THIRD_PARTY_NOTICES.md'):
            if is_link(REPO / name):
                raise RuntimeError('Source license must not be linked')
            shutil.copy2(REPO / name, licenses / name)
        shutil.copytree(REPO / 'LICENSES', licenses / 'third-party')
        if freeze_bytes is not None:
            (licenses / 'installed-distributions.txt').write_bytes(freeze_bytes)
        for name in ('app', 'licenses'):
            destination = output / name
            if destination.exists():
                shutil.rmtree(destination)
            os.replace(staging / name, destination)


def seal(output, name, version):
    # Interpreter/stdlib symlinks are copied as ordinary files for identical
    # manifest semantics on NTFS and APFS. No links outside the payload survive.
    links = [p for p in entries(output, allow_internal_file_links=True) if is_link(p)]
    for path in links:
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(output.resolve()):
            raise RuntimeError('Resource symlink escapes payload: ' + str(path))
        if not resolved.is_file():
            raise RuntimeError('Directory symlinks are not supported in payload')
        raw = resolved.read_bytes()
        mode = resolved.stat().st_mode
        path.unlink()
        path.write_bytes(raw)
        path.chmod(mode)
    inventory = list(entries(output))
    files = {p.relative_to(output).as_posix(): digest(p) for p in sorted(inventory)
             if p.is_file() and p != output / 'bundle-manifest.json'}
    verify_installed_versions(output)
    project = project_metadata()
    metadata = {'schema_version': 1, 'app_version': version, 'platform': name,
                'python': RUNTIMES[name]['python'], 'entrypoint': 'app/desktop_entry.py',
                'models': 'models', 'runtime_archive_sha256': RUNTIMES[name]['sha256'],
                'source_revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip(),
                'source_dirty': bool(subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=normal'], cwd=REPO, text=True).strip()),
                'source_project_version': project['version'],
                'build_tool_sha256': digest(Path(__file__).resolve()),
                'app_requirements': list(APP_REQUIREMENTS),
                'model_requirements': project['optional-dependencies']['models'],
                'installed_distributions': 'licenses/installed-distributions.txt',
                'directories': sorted(p.relative_to(output).as_posix() for p in inventory if p.is_dir()),
                'files': files}
    (output / 'bundle-manifest.json').write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'platform': name, 'files': len(files),
                      'manifest_sha256': digest(output / 'bundle-manifest.json'),
                      'bytes': sum(p.stat().st_size for p in output.rglob('*') if p.is_file())}))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=REPO / 'desktop/bundle')
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--model-cache', type=Path)
    parser.add_argument('--refresh-app', action='store_true')
    parser.add_argument('--version', default='1.2.5')
    args = parser.parse_args()
    name = target()
    output = prepare_output(args.output, name, refresh=args.refresh_app)
    python = output / RUNTIMES[name]['python']
    if args.refresh_app:
        stage_app(output, refresh=True)
        seal(output, name, args.version)
        return
    if (output / 'runtime').exists():
        raise RuntimeError('Build target already has a runtime; use a new output directory')
    with tempfile.TemporaryDirectory(prefix='wecfu-desktop-build-') as tmp:
        tmp = Path(tmp)
        archive = args.archive or tmp / 'python.tar.gz'
        if args.archive is None:
            url = 'https://github.com/astral-sh/python-build-standalone/releases/download/20261026/' + RUNTIMES[name]['file']
            urllib.request.urlretrieve(url, archive)
        if digest(archive) != RUNTIMES[name]['sha256']:
            raise RuntimeError('Portable Python archive checksum mismatch')
        with tarfile.open(archive) as packed:
            packed.extractall(tmp / 'unpacked', filter='data')
        shutil.copytree(tmp / 'unpacked/python', output / 'runtime', symlinks=False)
    env = clean_env()
    requirements = tomllib.loads((REPO / 'pyproject.toml').read_text())['project']['optional-dependencies']['models']
    subprocess.run([str(python), '-I', '-B', '-m', 'pip', 'install', '--no-compile',
                    '--index-url', 'https://pypi.org/simple', *APP_REQUIREMENTS, *requirements], env=env, check=True)
    stage_app(output)
    models = output / 'models'
    setup = [str(python), '-B', '-c',
             'import sys;sys.path.insert(0,sys.argv[1]);from wecfu.setup_models import main;'
             'sys.argv=["setup_models",*sys.argv[2:]];raise SystemExit(main())',
             str(output / 'app'), '--cache-dir', str(models)]
    if args.model_cache:
        setup += ['--offline-from', str(args.model_cache.resolve())]
    subprocess.run(setup, env=env, check=True)
    freeze = subprocess.check_output([str(python), '-I', '-B', '-m', 'pip', 'freeze'], env=env, text=True)
    (output / 'licenses/installed-distributions.txt').write_text(freeze, encoding='utf-8')
    seal(output, name, args.version)


if __name__ == '__main__':
    main()
