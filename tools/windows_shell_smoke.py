"""Installed native shell -> bundled host smoke, without UI automation or inference.

The disposable CI installation is started by its exact verified EXE. Process and
TCP metadata identify only that shell's child. The bootstrap capability stays in
memory, never in receipts/logs. Cleanup forcibly terminates the owned Job; this
does NOT test normal window close, rendering, Save As, or Explorer interaction.
"""
from __future__ import annotations

import ctypes
import hashlib
from http.cookiejar import CookieJar
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, HTTPCookieProcessor, ProxyHandler, Request, build_opener

TOTAL_SECONDS = 180
START_SECONDS = 120
HTTP_SECONDS = 30
MAX_RESPONSE = 1024 * 1024
ENGINE = 'sam2_local_v1'
SESSION = re.compile(r'^[0-9a-f]{32}$')
WORKSPACE = re.compile(r'^wecfu-desktop-session-[0-9a-f]{32}$')
SOURCES = [
    'https://learn.microsoft.com/en-us/windows/win32/cimwin32prov/win32-process',
    'https://learn.microsoft.com/en-us/powershell/module/nettcpip/get-nettcpconnection',
    'https://learn.microsoft.com/en-us/windows/win32/api/shellapi/nf-shellapi-commandlinetoargvw',
]

# This wrapper executes only after spawn_owned assigns it to its kill-on-close
# Job. The installed GUI executable and every descendant inherit that ownership.
# stdout/stderr from the app are deliberately not captured: they are not needed
# for this check and must not accidentally persist a launch capability.
WRAPPER = '''import json,pathlib,subprocess,sys
child=subprocess.Popen([sys.argv[1]],cwd=str(pathlib.Path(sys.argv[1]).parent),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
with open(sys.argv[2],"x",encoding="utf-8") as stream:
 json.dump({"pid":child.pid},stream)
raise SystemExit(child.wait())
'''

# Read-only local metadata. No window APIs, remote sessions, UI drivers or shell
# commands supplied by the product. Only numeric owned PIDs cross this boundary.
METADATA = r'''param([int]$ShellPid, [int]$OwnerPid)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
function Row($p) {
  if ($null -eq $p) { return $null }
  return @{ pid=[int]$p.ProcessId; parent=[int]$p.ParentProcessId;
    executable=[string]$p.ExecutablePath; command=[string]$p.CommandLine;
    created_ms=([DateTimeOffset]$p.CreationDate.ToUniversalTime()).ToUnixTimeMilliseconds() }
}
$shell = Get-CimInstance Win32_Process -Filter "ProcessId = $ShellPid"
if ($null -eq $shell -or $shell.ParentProcessId -ne $OwnerPid) { throw 'Owned shell absent' }
$children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $ShellPid AND Name = 'python.exe'")
if ($children.Count -gt 4) { throw 'Unexpected host inventory' }
$listeners = @()
foreach ($child in $children) {
  $listeners += @(Get-NetTCPConnection -OwningProcess $child.ProcessId -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { @{ pid=[int]$_.OwningProcess; address=[string]$_.LocalAddress; port=[int]$_.LocalPort } })
}
@{ shell=(Row $shell); children=@($children | ForEach-Object { Row $_ }); listeners=@($listeners) } |
  ConvertTo-Json -Depth 5 -Compress
'''


class SmokeFailure(RuntimeError):
    """Only fixed, nonsensitive failure messages may be persisted."""


def require(condition, message):
    if not condition:
        raise SmokeFailure(message)


def remaining(deadline, maximum):
    value = min(maximum, deadline - time.monotonic())
    require(value > 0, 'Installed shell smoke exceeded its bounded deadline')
    return value


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write('\n')


def command_line(command):
    """Use Windows' Unicode parser rather than guessing quoting/backslashes."""
    require(type(command) is str and 0 < len(command) <= 32768 and '\0' not in command,
            'Invalid installed host command metadata')
    shell = ctypes.WinDLL('shell32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    shell.CommandLineToArgvW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
    shell.CommandLineToArgvW.restype = ctypes.POINTER(ctypes.c_wchar_p)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    count = ctypes.c_int()
    result = shell.CommandLineToArgvW(command, ctypes.byref(count))
    require(bool(result), 'Cannot parse installed host command metadata')
    try:
        require(0 < count.value <= 32, 'Unexpected installed host argument count')
        return [result[index] for index in range(count.value)]
    finally:
        kernel.LocalFree(result)


def same_path(actual, expected):
    if type(actual) is not str or not actual:
        return False
    try:
        # Rust's canonical Windows paths use the extended prefix. Compare real
        # filesystem identity, not spelling, without stripping device prefixes.
        return Path(actual).samefile(Path(expected))
    except (OSError, ValueError):
        return False


def validate_snapshot(data, *, shell_pid, owner_pid, installed, bundle, manifest, temp_root,
                      launched_ms, expected_identity=None, parse=command_line):
    """Return an in-memory capability and a separate safe receipt identity."""
    require(type(data) is dict and set(data) == {'shell', 'children', 'listeners'}, 'Invalid process metadata schema')
    shell = data['shell']
    require(type(shell) is dict and shell.get('pid') == shell_pid and shell.get('parent') == owner_pid
            and same_path(shell.get('executable'), installed), 'Installed shell ownership/path differs')
    require(type(shell.get('created_ms')) is int and shell['created_ms'] >= launched_ms - 2000,
            'Installed shell creation identity differs')
    children, listeners = data['children'], data['listeners']
    require(type(children) is list and len(children) <= 4 and type(listeners) is list and len(listeners) <= 8,
            'Unexpected installed host metadata inventory')
    if not children:
        require(not listeners and expected_identity is None, 'Installed host disappeared')
        return None
    require(len(children) == 1, 'Installed shell did not create exactly one Python host')
    host = children[0]
    require(type(host) is dict and type(host.get('pid')) is int and host['pid'] > 0
            and host.get('parent') == shell_pid and same_path(host.get('executable'), bundle / manifest['python'])
            and type(host.get('created_ms')) is int and host['created_ms'] >= shell['created_ms'],
            'Installed child ownership/runtime differs')
    args = parse(host.get('command'))
    require(len(args) == 10 and same_path(args[0], bundle / manifest['python']) and args[1:3] == ['-I', '-B']
            and same_path(args[3], bundle / manifest['entrypoint'])
            and args[4] == '--resource-root' and same_path(args[5], bundle)
            and args[6] == '--session-id' and type(args[7]) is str and SESSION.fullmatch(args[7])
            and args[8] == '--workspace-root', 'Installed host command does not match the native contract')
    workspace = Path(args[9]).resolve()
    require(same_path(str(workspace.parent), temp_root) and WORKSPACE.fullmatch(workspace.name),
            'Installed shell used a workspace outside this test')
    identity = {'shell_pid': shell_pid, 'shell_created_ms': shell['created_ms'],
                'host_pid': host['pid'], 'host_created_ms': host['created_ms'],
                'runtime': str(bundle / manifest['python']), 'workspace': str(workspace)}
    if expected_identity is not None:
        require(identity == expected_identity, 'Installed process identity changed during the check')
    if not listeners:
        require(expected_identity is None, 'Installed loopback listener disappeared')
        return None
    require(len(listeners) == 1, 'Installed host has unexpected listening sockets')
    listener = listeners[0]
    require(type(listener) is dict and listener.get('pid') == host['pid'] and listener.get('address') == '127.0.0.1'
            and type(listener.get('port')) is int and 0 < listener['port'] <= 65535,
            'Installed host did not bind exactly one private IPv4 loopback socket')
    return {'session': args[7], 'origin': f"http://127.0.0.1:{listener['port']}", 'identity': identity}


def read_metadata(script, shell_pid, owner_pid, deadline):
    require(type(shell_pid) is int and shell_pid > 0 and type(owner_pid) is int and owner_pid > 0,
            'Invalid owned process identifier')
    powershell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    # Query output contains the host command/capability and is NEVER saved.
    result = subprocess.run([str(powershell), '-NoLogo', '-NoProfile', '-NonInteractive',
        '-File', str(script), str(shell_pid), str(owner_pid)], stdin=subprocess.DEVNULL,
        capture_output=True, timeout=remaining(deadline, 15), check=False)
    require(result.returncode == 0 and len(result.stdout) <= MAX_RESPONSE,
            'Cannot read owned Windows process/TCP metadata')
    try:
        return json.loads(result.stdout.decode('utf-8-sig'))
    except (ValueError, UnicodeError):
        raise SmokeFailure('Invalid owned Windows metadata response') from None


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise SmokeFailure('Installed service unexpectedly redirected a request')


def check_http(capability, deadline):
    origin, session = capability['origin'], capability['session']
    opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(CookieJar()), NoRedirect())
    records = []
    for label, route, expected in [('unauthorized_batches', '/api/batches', 403),
                                   ('session_bootstrap', '/?desktop_session=' + session, 200),
                                   ('empty_batches', '/api/batches', 200), ('ultra_available', '/api/config', 200)]:
        request = Request(origin + route, headers={'Origin': origin}, method='GET')
        before = time.monotonic()
        try:
            response = opener.open(request, timeout=remaining(deadline, 10))
        except HTTPError as error:
            response = error
        with response:
            raw = response.read(MAX_RESPONSE + 1)
            require(response.status == expected and len(raw) <= MAX_RESPONSE,
                    'Installed service returned an unexpected HTTP response')
        if label in ('empty_batches', 'ultra_available'):
            try:
                body = json.loads(raw)
            except ValueError:
                raise SmokeFailure('Installed service returned invalid configuration JSON') from None
            if label == 'empty_batches':
                require(body.get('batches') == [], 'Installed shell did not start with an empty workspace')
            else:
                require(body.get('default_model') == ENGINE
                        and body.get('models', {}).get('sam2', {}).get('available') is True,
                        'Ultra is unavailable from the actual installed shell')
        records.append({'check': label, 'status': expected, 'seconds': time.monotonic() - before})
    return records


def run(installed, bundle, manifest, output, expected_exe_sha256, outer_deadline):
    """Always retain a redacted receipt, including failures and forced cleanup."""
    from wecfu.platform_runtime import spawn_owned, stop_owned
    started = time.monotonic()
    deadline = min(started + TOTAL_SECONDS, outer_deadline)
    output.mkdir(parents=True, exist_ok=False)
    record = {'status': 'failed', 'mode': 'installed_shell_boot_and_forced_owned_cleanup',
              'total_budget_seconds': TOTAL_SECONDS, 'model_requests': 0, 'model_retries': 0,
              'ui_automation': False, 'graceful_close_tested': False, 'metadata_sources': SOURCES,
              'limitations': ['Process/API smoke only; no rendered WebView, Save As, Explorer, drag/drop or Windows11 GUI acceptance.',
                              'Forced Job termination is tested. Session files are retained; normal window-close cleanup is not tested.']}
    process = None
    try:
        require(sys.platform == 'win32', 'Installed native shell smoke is Windows-only')
        require(installed.is_file() and sha(installed) == expected_exe_sha256, 'Installed EXE differs before native startup')
        manifest_sha = sha(bundle / 'bundle-manifest.json')
        record.update(installed_exe=str(installed), installed_exe_sha256=expected_exe_sha256,
                      manifest_sha256=manifest_sha, app_version=manifest['app_version'])
        temp_root = output / 'session-temp'; temp_root.mkdir()
        wrapper = output / 'shell-child.py'; wrapper.write_text(WRAPPER, encoding='utf-8')
        metadata = output / 'process-metadata.ps1'; metadata.write_text(METADATA, encoding='utf-8-sig')
        launch = output / 'launch.json'
        env = {k:v for k,v in os.environ.items() if not k.upper().startswith(('PYTHON', 'WECFU_', 'PIP_'))}
        env.update(PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1',
                   TMP=str(temp_root), TEMP=str(temp_root), TMPDIR=str(temp_root))
        launched_ms = int(time.time() * 1000)
        process = spawn_owned([sys.executable, '-B', str(wrapper), str(installed), str(launch)],
                              cwd=installed.parent, env=env, stdin=subprocess.PIPE,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        process.stdin.close()
        startup_deadline = min(started + START_SECONDS, deadline - 15)
        shell_pid = None; capability = None
        while time.monotonic() < startup_deadline:
            require(process.poll() is None, 'Installed shell exited before readiness')
            if shell_pid is None and launch.is_file():
                try:
                    data = json.loads(launch.read_text(encoding='utf-8'))
                except ValueError:  # The wrapper may still be finishing its tiny write.
                    data = None
                if data is not None:
                    require(type(data) is dict and set(data) == {'pid'} and type(data['pid']) is int and data['pid'] > 0,
                            'Invalid installed shell launch receipt')
                    shell_pid = data['pid']
            if shell_pid is not None:
                raw = read_metadata(metadata, shell_pid, process.pid, startup_deadline)
                capability = validate_snapshot(raw, shell_pid=shell_pid, owner_pid=process.pid,
                    installed=installed, bundle=bundle, manifest=manifest, temp_root=temp_root, launched_ms=launched_ms)
                if capability is not None:
                    break
            time.sleep(min(0.5, remaining(startup_deadline, 0.5)))
        require(capability is not None, 'Installed shell did not become ready within 120 seconds')
        record['ready_seconds'] = time.monotonic() - started
        record['identity'] = capability['identity']
        record['http_checks'] = check_http(capability, min(time.monotonic() + HTTP_SECONDS, deadline - 5))
        require(process.poll() is None, 'Installed shell exited during HTTP checks')
        after = validate_snapshot(read_metadata(metadata, shell_pid, process.pid, deadline - 5),
            shell_pid=shell_pid, owner_pid=process.pid, installed=installed, bundle=bundle, manifest=manifest,
            temp_root=temp_root, launched_ms=launched_ms, expected_identity=capability['identity'])
        require(after is not None and after['origin'] == capability['origin'] and after['session'] == capability['session'],
                'Installed host session/listener changed during the check')
        require(sha(installed) == expected_exe_sha256 and sha(bundle / 'bundle-manifest.json') == manifest_sha,
                'Installed source binding changed during native smoke')
        record['status'] = 'passed'
    except Exception as error:
        # Network/OS exceptions can embed the bootstrap URL or command line.
        # Only our fixed SmokeFailure messages are safe to publish.
        record['error'] = str(error) if isinstance(error, SmokeFailure) else 'Installed shell smoke failed; raw diagnostics withheld to protect the session capability'
        record['error_type'] = type(error).__name__
    finally:
        if process is not None:
            try:
                # Cleanup still runs if readiness already exhausted the budget.
                # An over-budget receipt fails below; never strand the owned Job.
                stop_owned(process, timeout=5)
                record['forced_job_cleanup'] = {'all_owned_processes_retired': True, 'graceful': False,
                                                'session_files_retained': True}
            except Exception as error:
                record.update(status='failed', cleanup_error_type=type(error).__name__,
                              cleanup_error='Could not confirm forced retirement of the test-owned Job')
        record['elapsed_seconds'] = time.monotonic() - started
        if time.monotonic() > deadline:
            record.update(status='failed', error='Installed shell smoke exceeded its bounded deadline')
        save(output / 'result.json', record)
    require(record['status'] == 'passed', 'Installed native shell startup smoke failed; see its redacted receipt')
    return {'path': str(output / 'result.json'), 'sha256': sha(output / 'result.json'),
            'mode': record['mode'], 'model_requests': 0, 'seconds': record['elapsed_seconds']}
