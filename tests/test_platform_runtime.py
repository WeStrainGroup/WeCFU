"""Platform contracts: fake Win32 API tests plus native OS/process tests.

Mocked Windows cases do not claim Windows OS or packaging validation.
"""
import ctypes
import errno
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest
from wecfu import platform_runtime as rt


class Process:
    pid = 43210
    _handle = 123

    def __init__(self, events):
        self.events = events
        self.returncode = None
        self.stdin, self.stdout, self.stderr = io.BytesIO(), io.BytesIO(), io.BytesIO()

    def poll(self):
        return self.returncode

    def kill(self):
        self.events.append('kill')
        self.returncode = -1

    def wait(self, timeout):
        self.events.append('wait')
        self.returncode = 0 if self.returncode is None else self.returncode
        return self.returncode


class API:
    def __init__(self, events):
        self.events = events
        self.count = 0
        self.memory_result = (100, 150)

    def create_job(self):
        self.events.append('job')
        return 321

    def assign(self, job, process):
        assert process.stdin.getvalue() == b''  # no worker execution before ownership
        self.events.append('assign')

    def terminate(self, job):
        self.events.append('terminate')

    def active(self, job):
        self.events.append('active')
        return self.count

    def close(self, job):
        self.events.append('close')

    def memory(self, handle):
        assert handle == 123
        self.events.append('memory')
        return self.memory_result

    def self_memory(self):
        return self.memory_result


@pytest.fixture
def windows(monkeypatch):
    events = []
    process, api = Process(events), API(events)
    calls = []
    def popen(command, **kwargs):
        events.append('spawn')
        calls.append((command, kwargs))
        return process
    monkeypatch.setattr(rt.sys, 'platform', 'win32')
    monkeypatch.setattr(rt, '_windows_api', lambda: api)
    monkeypatch.setattr(rt.subprocess, 'Popen', popen)
    monkeypatch.setattr(rt, '_OWNED', {})
    return process, api, events, calls


def test_windows_gate_owns_before_release_and_retirement_is_idempotent(windows):
    p, api, events, calls = windows
    assert rt.spawn_owned(['python.exe', '-B', 'worker.py', '--serve'], stdin=subprocess.PIPE) is p
    assert events == ['job', 'spawn', 'assign']
    command, kwargs = calls[0]
    assert command == ['python.exe', '-B', '-c', rt._WINDOWS_GATE, 'worker.py', '--serve']
    assert kwargs['bufsize'] == 0 and kwargs['creationflags'] == 0x08000000
    assert p.stdin.getvalue() == b'G'
    assert rt.sampled_rss(p.pid) == 100
    assert rt.self_peak_rss() == 150
    rt.stop_owned(p)
    assert events[-4:] == ['terminate', 'wait', 'active', 'close']
    assert rt._OWNED == {}
    before = events.copy()
    rt.stop_owned(p)
    assert events == before


def test_assignment_and_job_termination_failures_still_kill_gated_child(windows):
    p, api, events, _ = windows
    def denied(*args):
        raise OSError(errno.EPERM, 'synthetic assign/terminate denied')
    api.assign = api.terminate = denied
    with pytest.raises(OSError):
        rt.spawn_owned(['python.exe', '-B', 'worker.py'])
    assert 'kill' in events and 'wait' in events and events[-1] == 'close'
    assert p.stdin.closed and p.stdout.closed and p.stderr.closed
    assert rt._OWNED == {}


def test_spawn_failure_closes_created_job(windows, monkeypatch):
    p, api, events, _ = windows
    def bad(*args, **kwargs):
        raise FileNotFoundError('synthetic missing Python')
    monkeypatch.setattr(rt.subprocess, 'Popen', bad)
    with pytest.raises(FileNotFoundError):
        rt.spawn_owned(['python.exe', '-B', 'worker.py'])
    assert events == ['job', 'terminate', 'close']


def test_cleanup_timeout_does_not_skip_job_close(windows):
    p, api, events, _ = windows
    api.assign = lambda *a: (_ for _ in ()).throw(OSError('synthetic assignment fail'))
    p.wait = lambda **kw: (_ for _ in ()).throw(subprocess.TimeoutExpired('synthetic', 4))
    with pytest.raises(subprocess.TimeoutExpired):
        rt.spawn_owned(['python.exe', '-B', 'worker.py'])
    assert events[-1] == 'close' and not rt._OWNED


def test_unowned_or_recycled_pid_cannot_be_sampled_or_stopped(windows):
    p, api, events, _ = windows
    with pytest.raises(RuntimeError, match='unowned'):
        rt.sampled_rss(p.pid)
    rt.spawn_owned(['python.exe', '-B', 'worker.py'])
    impostor = Process(events)
    with pytest.raises(RuntimeError, match='unowned'):
        rt.stop_owned(impostor)
    api.memory_result = (0, 150)
    with pytest.raises(RuntimeError, match='working-set'):
        rt.sampled_rss(p.pid)
    p.returncode = 0
    with pytest.raises(ProcessLookupError):
        rt.sampled_rss(p.pid)


def test_job_active_timeout_preserves_handle_for_later_cleanup(windows):
    p, api, events, _ = windows
    rt.spawn_owned(['python.exe', '-B', 'worker.py'])
    api.count = 1
    with pytest.raises(subprocess.TimeoutExpired):
        rt.stop_owned(p, timeout=0)
    assert p.pid in rt._OWNED and 'close' not in events
    api.count = 0
    rt.stop_owned(p)
    assert not rt._OWNED


@pytest.mark.parametrize('kwargs', [{'text': True}, {'encoding': 'utf8'}, {'stdin': subprocess.DEVNULL}, {'shell': True}, {'creationflags': 4}])
def test_windows_rejects_protocol_or_ownership_overrides(windows, kwargs):
    with pytest.raises(ValueError):
        rt.spawn_owned(['python.exe', '-B', 'worker.py'], **kwargs)
    assert windows[2] == []


def test_win64_structure_abi_and_fixed_flags():
    if ctypes.sizeof(ctypes.c_void_p) != 8:
        pytest.skip('x64 ABI contract')
    assert ctypes.sizeof(rt._MemoryCounters) == 72
    assert ctypes.sizeof(rt._BasicLimits) == 64
    assert ctypes.sizeof(rt._ExtendedLimits) == 144
    assert ctypes.sizeof(rt._JobAccounting) == 48
    events = []
    api = object.__new__(rt._WindowsAPI)
    def set_info(job, info_class, pointer, size):
        limits = ctypes.cast(pointer, ctypes.POINTER(rt._ExtendedLimits)).contents
        events.append((info_class, size, limits.BasicLimitInformation.LimitFlags))
        return 1
    api.kernel = SimpleNamespace(CreateJobObjectW=lambda *a: 321, SetInformationJobObject=set_info)
    assert api.create_job() == 321
    assert events == [(9, 144, 0x2000)]


def test_gate_reads_exact_one_byte_and_keeps_worker_argv(tmp_path):
    # Real CPython/pipe test on this host; not a Windows Job API test.
    worker = tmp_path / 'worker.py'
    worker.write_text('import json,sys\nprint(json.dumps({"line":sys.stdin.buffer.readline().decode(),"args":sys.argv[1:]}))\n')
    out = subprocess.run([sys.executable, '-B', '-c', rt._WINDOWS_GATE, str(worker), '--serve'],
        input=b'G{"request":1}\n', capture_output=True, timeout=5, check=True)
    assert json.loads(out.stdout) == {'line': '{"request":1}\n', 'args': ['--serve']}
    denied = subprocess.run([sys.executable, '-B', '-c', rt._WINDOWS_GATE, str(worker)],
        input=b'X', capture_output=True, timeout=5)
    assert denied.returncode == 125 and denied.stdout == b''


@pytest.mark.skipif(sys.platform == 'win32', reason='native POSIX group contract')
@pytest.mark.parametrize('desktop', [False, True])
def test_native_posix_worker_group_and_exact_stop(monkeypatch, desktop):
    if desktop:
        monkeypatch.setenv('WECFU_DESKTOP_MANAGED', '1')
    else:
        monkeypatch.delenv('WECFU_DESKTOP_MANAGED', raising=False)
    child = rt.spawn_owned([sys.executable, '-B', '-c', 'import time;time.sleep(30)'])
    try:
        assert os.getpgid(child.pid) == (os.getpgrp() if desktop else child.pid)
        rt.stop_owned(child)
        assert child.poll() is not None
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)


def test_windows_paths_and_lock_byte_protocol(monkeypatch, tmp_path):
    monkeypatch.setattr(rt.sys, 'platform', 'win32')
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'app-data'))
    assert rt.default_model_home() == tmp_path / 'app-data/WeCFU/models'
    assert rt.venv_python(tmp_path) == tmp_path / 'Scripts/python.exe'
    events = []
    held = False
    def locking(fd, op, size):
        nonlocal held
        assert os.lseek(fd, 0, os.SEEK_CUR) == 0 and size == 1
        events.append(op)
        if op == 1 and held:
            raise OSError(errno.EACCES, 'synthetic lock held')
        held = op == 1
    monkeypatch.setitem(sys.modules, 'msvcrt', SimpleNamespace(locking=locking, LK_NBLCK=1, LK_UNLCK=2))
    lock = tmp_path / 'setup.lock'
    with rt.exclusive_file_lock(lock):
        assert lock.read_bytes() == b'\0'
        with pytest.raises(RuntimeError, match='another WeCFU process'):
            with rt.exclusive_file_lock(lock):
                pass
    with rt.exclusive_file_lock(lock):
        pass
    assert events == [1, 1, 2, 1, 2]


@pytest.mark.skipif(sys.platform != 'win32', reason='requires real Windows kernel and Python')
def test_native_windows_job_owns_kills_descendants_and_reads_rss(tmp_path):
    worker = tmp_path / 'tree.py'
    ready = tmp_path / 'descendant-ready'
    worker.write_text('import subprocess,sys,time\nfrom pathlib import Path\np=subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"])\nPath(' + repr(str(ready)) + ').write_text(str(p.pid))\ntime.sleep(30)\n')
    p = rt.spawn_owned([sys.executable, '-B', str(worker)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        # Bounded file handshake confirms a real descendant, without a blocking pipe.
        deadline = time.monotonic() + 5
        while not ready.exists() and p.poll() is None and time.monotonic() < deadline:
            time.sleep(.01)
        assert ready.exists()
        _, api, job = rt._OWNED[p.pid]
        assert api.active(job) >= 2
        assert rt.sampled_rss(p.pid) > 0
        rt.stop_owned(p)
        assert p.poll() is not None and p.pid not in rt._OWNED
    finally:
        if p.pid in rt._OWNED:
            rt.stop_owned(p)
        for stream in (p.stdin, p.stdout, p.stderr):
            stream.close()
