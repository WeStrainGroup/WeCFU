"""Bounded Windows NSIS installation + installed-backend synthetic acceptance.

Only run on a disposable, clean Windows runner. Existing WeCFU registration,
installation paths or shortcuts cause refusal. No elevation, uninstall, model
retry, downloads, photographs or UI automation. The isolated installation is
retained for diagnosis and discarded with the CI runner, not recursively deleted.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import shutil
import subprocess
import sys
import tempfile
import time

REPO = Path(__file__).resolve().parents[1]
TOTAL_SECONDS = 1200
INSTALL_SECONDS = 300
API_SECONDS = 600
MAX_MANIFEST = 16 * 1024**2
UNINSTALL = r'Software\Microsoft\Windows\CurrentVersion\Uninstall'
INSTALL_CHILD = 'import subprocess,sys\nraise SystemExit(subprocess.call(sys.argv[1],executable=sys.argv[2],stdin=subprocess.DEVNULL))\n'
NSIS_DOC = 'https://nsis.sourceforge.io/Docs/Chapter3.html#3.2.1'
TAURI_CLI_VERSION = '2.12.4'
UNKNOWN_BUNDLE_MARKER = b'__TAURI_BUNDLE_TYPE_VAR_UNK'
NSIS_BUNDLE_MARKER = b'__TAURI_BUNDLE_TYPE_VAR_NSS'
MAX_SHELL_BYTES = 256 * 1024**2
# Tauri patches this marker before packaging, then restores the build EXE.
# Only this exact transformation is permitted; all installed bytes are hashed.
TAURI_PATCH_SOURCE = {
    'url': 'https://raw.githubusercontent.com/tauri-apps/tauri/tauri-cli-v2.12.4/crates/tauri-bundler/src/bundle.rs',
    'sha256': '91c8387ccb2e52388cdcfeccfd23f69dac5439aba397d464b1d5446153fdc82e',
}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def check_time(deadline):
    require(time.monotonic() < deadline, 'Installation acceptance exceeded 1200-second total budget')


def is_link(path):
    return path.is_symlink() or getattr(path, 'is_junction', lambda: False)()


def digest(path, deadline):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024**2), b''):
            check_time(deadline)
            value.update(block)
    return value.hexdigest()


def check_bundler_version(repo):
    lock_path = repo / 'desktop/package-lock.json'
    cli_path = repo / 'desktop/node_modules/@tauri-apps/cli/package.json'
    lock = json.loads(lock_path.read_text(encoding='utf-8'))
    cli = json.loads(cli_path.read_text(encoding='utf-8'))
    require(lock['packages']['node_modules/@tauri-apps/cli']['version'] == TAURI_CLI_VERSION
            and cli['version'] == TAURI_CLI_VERSION, 'Unreviewed Tauri binary patching version')
    return [lock_path, cli_path]


def nsis_shell_identity(built, deadline):
    """Derive the complete NSIS EXE hash without changing the build artifact."""
    marker = UNKNOWN_BUNDLE_MARKER
    require(len(marker) == len(NSIS_BUNDLE_MARKER) == 27, 'Invalid bundle marker contract')
    size = built.stat().st_size
    require(0 < size <= MAX_SHELL_BYTES, 'Build executable exceeds shell size budget')
    original = hashlib.sha256()
    offsets, carry, total = [], b'', 0
    with built.open('rb') as stream:
        for block in iter(lambda: stream.read(1024**2), b''):
            check_time(deadline)
            require(total + len(block) <= size, 'Build executable changed while hashing')
            original.update(block)
            data = carry + block
            start = 0
            while (index := data.find(marker, start)) >= 0:
                offsets.append(total - len(carry) + index)
                require(len(offsets) <= 1, 'Duplicate build bundle marker')
                start = index + 1
            total += len(block)
            carry = data[-(len(marker)-1):]
    require(total == size and len(offsets) == 1, 'Missing build bundle marker or changed size')
    offset = offsets[0]
    expected, reread, total = hashlib.sha256(), hashlib.sha256(), 0
    with built.open('rb') as stream:
        for block in iter(lambda: stream.read(1024**2), b''):
            check_time(deadline)
            require(total + len(block) <= size, 'Build executable changed while deriving NSIS hash')
            reread.update(block)
            left, right = max(total, offset), min(total + len(block), offset + len(marker))
            if left < right:
                block = block[:left-total] + NSIS_BUNDLE_MARKER[left-offset:right-offset] + block[right-total:]
            expected.update(block)
            total += len(block)
    require(total == size and reread.digest() == original.digest(), 'Build executable changed during NSIS derivation')
    return {'tauri_cli_version': TAURI_CLI_VERSION, 'source': TAURI_PATCH_SOURCE,
            'marker_offset': offset, 'bytes': size, 'original_sha256': original.hexdigest(),
            'expected_installed_sha256': expected.hexdigest(),
            'transformation': 'one_27_byte_UNK_to_NSS_marker_only'}


def verify_installed_shell(destination, built, identity, deadline, receipt):
    # Record the root inventory BEFORE any EXE assertion, even for a wrong name.
    whole = inventory(destination, deadline)
    extras = {name: digest(path, deadline) for name, path in whole.items() if not name.startswith('bundle/')}
    receipt['non_bundle_installed_files'] = extras
    installed = destination / built.name
    exists = built.name in whole
    facts = {'path': str(installed), 'expected_basename': built.name, 'exists': exists,
             'expected_sha256': identity['expected_installed_sha256'], 'expected_bytes': identity['bytes'],
             'sha256': extras.get(built.name), 'bytes': installed.stat().st_size if exists else None}
    receipt['installed_exe'] = facts
    require(exists, 'Installed application executable is missing at the exact build basename')
    require(facts['bytes'] == identity['bytes'], 'Installed application executable size differs from this build')
    require(facts['sha256'] == identity['expected_installed_sha256'],
            'Installed application executable differs from the exact Tauri NSIS marker patch')
    return installed


def save(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def inventory(root, deadline):
    require(root.is_dir() and not is_link(root), 'Missing or linked installation directory')
    files = {}
    for directory, folders, names in os.walk(root, followlinks=False):
        check_time(deadline)
        for name in folders + names:
            path = Path(directory) / name
            require(not is_link(path), 'Installed payload contains a link or junction')
        for name in names:
            path = Path(directory) / name
            require(path.is_file(), 'Nonregular installed entry')
            files[path.relative_to(root).as_posix()] = path
    return files


def manifest_document(raw):
    require(len(raw) <= MAX_MANIFEST, 'Manifest exceeds size budget')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'Duplicate manifest key')
            result[key] = value
        return result
    data = json.loads(raw, object_pairs_hook=unique)
    require(type(data['schema_version']) is int and data['schema_version'] == 1 and data['platform'] == 'win32-x64'
            and data['python'] == 'runtime/python.exe'
            and data['entrypoint'] == 'app/desktop_entry.py', 'Not the fixed Windows desktop payload')
    files = data['files']
    require(type(files) is dict and files and len(files) <= 100000, 'Invalid manifest files')
    folded = set()
    for name, value in files.items():
        require(type(name) is str and name and '\\' not in name and ':' not in name
                and not PurePosixPath(name).is_absolute()
                and all(p not in ('', '.', '..') for p in name.split('/')),
                'Unsafe manifest path')
        require(name.casefold() not in folded, 'Case-colliding manifest path')
        folded.add(name.casefold())
        require(type(value) is str and len(value) == 64 and all(c in '0123456789abcdef' for c in value),
                'Invalid manifest digest')
    require(data['python'] in files and data['entrypoint'] in files, 'Runtime/entrypoint not pinned')
    return data


def verify_payload(root, raw_manifest, deadline):
    manifest = manifest_document(raw_manifest)
    actual = inventory(root, deadline)
    require(set(actual) == set(manifest['files']) | {'bundle-manifest.json'}, 'Installed bundle inventory mismatch')
    require(actual['bundle-manifest.json'].read_bytes() == raw_manifest, 'Installed manifest differs from build')
    total = 0
    for relative, expected in manifest['files'].items():
        check_time(deadline)
        require(digest(actual[relative], deadline) == expected, 'Installed payload hash mismatch: ' + relative)
        total += actual[relative].stat().st_size
    return {'files': len(manifest['files']), 'bytes': total,
            'manifest_sha256': hashlib.sha256(raw_manifest).hexdigest(), 'app_version': manifest['app_version']}


def nsis_command(installer, destination):
    # /D is parsed by NSIS itself: LAST, absolute, and UNQUOTED even with spaces.
    # Popen gets one Windows command line and an explicit executable, no shell.
    exe, target = str(installer), str(destination)
    require(PureWindowsPath(exe).is_absolute() and PureWindowsPath(target).is_absolute(),
            'NSIS requires absolute Windows paths')
    require(not any(c in exe + target for c in '\r\n\0"') and not target.endswith((' ', '.')),
            'Unsafe NSIS command path')
    return subprocess.list2cmdline([exe]) + ' /S /D=' + target


def existing_registrations(registry, deadline):
    found = []
    for hive_name in ('HKEY_CURRENT_USER', 'HKEY_LOCAL_MACHINE'):
        hive = getattr(registry, hive_name)
        for view in (registry.KEY_WOW64_32KEY, registry.KEY_WOW64_64KEY):
            flags = registry.KEY_READ | view
            for key in (r'Software\WeCFU', r'Software\org.westraingroup.wecfu'):
                try:
                    with registry.OpenKey(hive, key, 0, flags):
                        found.append({'hive': hive_name, 'view': view, 'key': key})
                except FileNotFoundError:
                    pass
            try:
                parent = registry.OpenKey(hive, UNINSTALL, 0, flags)
            except FileNotFoundError:
                continue
            with parent:
                count = registry.QueryInfoKey(parent)[0]
                require(count <= 10000, 'Uninstall registry inventory exceeds budget')
                for index in range(count):
                    check_time(deadline)
                    name = registry.EnumKey(parent, index)
                    with registry.OpenKey(parent, name) as key:
                        values = {}
                        for field in ('DisplayName', 'InstallLocation', 'UninstallString'):
                            try:
                                values[field] = registry.QueryValueEx(key, field)[0]
                            except FileNotFoundError:
                                pass
                    if 'wecfu' in json.dumps([name, values], ensure_ascii=False).casefold():
                        found.append({'hive': hive_name, 'view': view, 'key': UNINSTALL + '\\' + name,
                                      'values': values})
    return found


def preflight_existing(registry, env, deadline):
    registrations = existing_registrations(registry, deadline)
    paths = []
    for variable in ('LOCALAPPDATA', 'ProgramFiles', 'ProgramFiles(x86)'):
        if env.get(variable):
            paths.extend((Path(env[variable]) / 'WeCFU', Path(env[variable]) / 'Programs/WeCFU'))
    for variable in ('APPDATA', 'PROGRAMDATA'):
        if env.get(variable):
            start = Path(env[variable]) / 'Microsoft/Windows/Start Menu/Programs'
            paths.extend((start / 'WeCFU', start / 'WeCFU.lnk'))
    for variable in ('USERPROFILE', 'PUBLIC', 'OneDrive'):
        if env.get(variable):
            paths.append(Path(env[variable]) / 'Desktop/WeCFU.lnk')
    # Honor redirected shell folders rather than guessing that Desktop is local.
    for hive in (registry.HKEY_CURRENT_USER, registry.HKEY_LOCAL_MACHINE):
        try:
            key = registry.OpenKey(hive, r'Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders')
        except FileNotFoundError:
            continue
        with key:
            for field in ('Desktop', 'Common Desktop', 'Programs', 'Common Programs'):
                try:
                    value = registry.QueryValueEx(key, field)[0]
                except FileNotFoundError:
                    continue
                require(type(value) is str, 'Invalid shell-folder registration')
                paths.extend((Path(value) / 'WeCFU.lnk', Path(value) / 'WeCFU'))
    present = sorted({str(p) for p in paths if p.exists() or is_link(p)})
    require(not registrations and not present, 'Existing WeCFU registration/path/shortcut; refusing installation')
    return {'registrations': registrations, 'present_paths': present, 'checked_paths': sorted({str(p) for p in paths})}


def run_owned(command, folder, deadline, cap, name):
    # The gate assigns the Python wrapper to a Job BEFORE it starts the NSIS or
    # API child, so timeout cleanup covers descendants as well as the wrapper.
    from wecfu.platform_runtime import spawn_owned, stop_owned
    check_time(deadline)
    timeout = min(cap, deadline - time.monotonic())
    env = {k:v for k,v in os.environ.items() if not k.startswith(('PYTHON', 'WECFU_', 'PIP_'))}
    env.update(PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1')
    process = None
    started = time.monotonic()
    try:
        with (folder / (name + '.stdout.log')).open('xb') as stdout, (folder / (name + '.stderr.log')).open('xb') as stderr:
            process = spawn_owned(command, cwd=REPO, env=env, stdin=subprocess.PIPE, stdout=stdout, stderr=stderr)
            process.stdin.close()
            code = process.wait(timeout=timeout)
        require(code == 0, name + ' returned nonzero exit: ' + str(code))
        check_time(deadline)
        return {'exit_code': code, 'seconds': time.monotonic() - started, 'timeout_seconds': timeout}
    finally:
        if process is not None:
            stop_owned(process, timeout=4)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installer', type=Path, required=True)
    parser.add_argument('--built-exe', type=Path, required=True)
    parser.add_argument('--source-bundle', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve(); out.mkdir(parents=True, exist_ok=False)
    started = time.monotonic(); deadline = started + TOTAL_SECONDS
    receipt = {'status': 'failed', 'explicit_synthetic': True, 'native_windows_execution': sys.platform == 'win32',
               'total_budget_seconds': TOTAL_SECONDS, 'model_retry': False, 'automatic_uninstall': False,
               'limitations': ['CLI silent installation and installed backend; native WebView interaction/manual clean Windows11 acceptance remains separate',
                              'Installer may register this new per-user app/shortcuts; test only on a disposable runner. The installation is retained.'],
               'nsis_command_contract': NSIS_DOC}
    try:
        require(sys.platform == 'win32', 'Installer acceptance is Windows-only; no install was attempted')
        import winreg
        sys.path.insert(0, str(REPO))
        installer, built, source = args.installer.resolve(), args.built_exe.resolve(), args.source_bundle.resolve()
        require(installer.is_file() and built.is_file() and not is_link(args.installer) and not is_link(args.built_exe)
                and installer.suffix.lower() == built.suffix.lower() == '.exe', 'Missing/linked build artifacts')
        receipt['preflight'] = preflight_existing(winreg, os.environ, deadline)
        manifest_path = source / 'bundle-manifest.json'
        require(manifest_path.stat().st_size <= MAX_MANIFEST, 'Manifest exceeds size budget')
        raw_manifest = manifest_path.read_bytes()
        receipt['source_payload'] = verify_payload(source, raw_manifest, deadline)
        save(out / 'source-manifest.json', json.loads(raw_manifest))
        bundler_files = check_bundler_version(REPO)
        receipt['inputs'] = {str(p): digest(p, deadline) for p in (installer, built, Path(__file__), REPO/'tools/desktop_acceptance.py', *bundler_files)}
        receipt['shell_derivation'] = nsis_shell_identity(built, deadline)
        require(receipt['shell_derivation']['original_sha256'] == receipt['inputs'][str(built)],
                'Build executable changed before installation')
        install_parent = Path(tempfile.mkdtemp(prefix='WeCFU install 验证 '))
        destination = install_parent / 'WeCFU isolated'
        receipt['isolated_install_directory'] = str(destination)
        require(not destination.exists() and not is_link(destination), 'Install destination already exists')
        require(shutil.disk_usage(install_parent).free >= receipt['source_payload']['bytes'] + 512*1024**2,
                'Insufficient temporary disk for one isolated installation')
        command = nsis_command(installer, destination)
        receipt['installer_command'] = command
        wrapper = out / 'install-child.py'; wrapper.write_text(INSTALL_CHILD, encoding='utf-8')
        # Recheck immediately before executing; never let NSIS upgrade an existing installation.
        preflight_existing(winreg, os.environ, deadline)
        receipt['installation'] = run_owned([sys.executable, '-B', str(wrapper), command, str(installer)],
                                            out, deadline, INSTALL_SECONDS, 'installer')
        installed_bundle = destination / 'bundle'
        receipt['installed_payload'] = verify_payload(installed_bundle, raw_manifest, deadline)
        installed_exe = verify_installed_shell(destination, built, receipt['shell_derivation'], deadline, receipt)
        api_output = out / 'installed-api'
        receipt['api_process'] = run_owned([sys.executable, '-B', str(REPO/'tools/desktop_acceptance.py'),
            '--bundle', str(installed_bundle), '--output', str(api_output)], out, deadline, API_SECONDS, 'installed-api')
        # The acceptance writer emits UTF-8, including the deliberately Unicode
        # installation path. Windows' legacy locale decoder is not its format.
        result = json.loads((api_output/'result.json').read_text(encoding='utf-8'))
        manifest = manifest_document(raw_manifest)
        require(result['status'] == 'passed' and result['mode'] == 'two_image_real_SAM'
                and result['explicit_synthetic'] is True and result['real_model_requests'] == 2
                and result['real_model_request_attempts'] == 2
                and result['manifest_sha256'] == receipt['source_payload']['manifest_sha256']
                and result['app_version'] == manifest['app_version']
                and Path(result['actual_runtime']['executable']).resolve() == (installed_bundle / manifest['python']).resolve(),
                'Installed API receipt is not the required complete two-image real-runtime acceptance')
        for relative, expected in result['files'].items():
            path = api_output / relative
            require(path.resolve().is_relative_to(api_output.resolve()) and digest(path, deadline) == expected,
                    'Installed API evidence changed')
        receipt['installed_api_receipt'] = {'path':str(api_output/'result.json'), 'sha256':digest(api_output/'result.json', deadline),
                                           'actual_runtime':result['actual_runtime'],'model_requests':2}
        require(digest(installer, deadline) == receipt['inputs'][str(installer)]
                and digest(built, deadline) == receipt['inputs'][str(built)]
                and digest(installed_exe, deadline) == receipt['shell_derivation']['expected_installed_sha256']
                and all(digest(path, deadline) == receipt['inputs'][str(path)] for path in bundler_files)
                and (installed_bundle/'bundle-manifest.json').read_bytes() == raw_manifest,
                'Installer or installed source binding changed during acceptance')
        receipt['status'] = 'passed'
    except Exception as exc:
        receipt.update(error_type=type(exc).__name__, error=str(exc))
    finally:
        receipt['elapsed_seconds'] = time.monotonic() - started
        if receipt['elapsed_seconds'] > TOTAL_SECONDS:
            receipt.update(status='failed', error='Total acceptance budget exceeded')
        save(out / 'result.json', receipt)
    print(json.dumps({'status':receipt['status'], 'receipt':str(out/'result.json')}))
    return 0 if receipt['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
