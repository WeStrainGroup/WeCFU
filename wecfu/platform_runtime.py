"""OS services for owned SAM workers; no numeric/model code or downloads.

Windows working-set samples are resident bytes, not a private-commit hard cap.
Every Windows worker belongs to a kill-on-close Job before its script executes.
Only processes created here may be sampled or terminated through that interface.
"""
from __future__ import annotations

from contextlib import contextmanager
import ctypes
import errno
import os
import platform
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time


def platform_machine():
    return platform.machine()


def venv_python(folder):
    return Path(folder) / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')


def default_model_home():
    if sys.platform == 'win32':
        return Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData/Local') / 'WeCFU/models'
    if sys.platform == 'darwin':
        return Path.home() / 'Library/Caches/WeCFU/models'
    return Path(os.environ.get('XDG_CACHE_HOME', str(Path.home() / '.cache'))) / 'wecfu/models'


def is_link(path):
    path = Path(path)
    return path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction())


@contextmanager
def exclusive_file_lock(path):
    """Nonblocking OS lock; a crashed owner never leaves a stale held lock."""
    path = Path(path)
    if is_link(path):
        raise RuntimeError('Runtime lock must not be a link')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        if sys.platform == 'win32':
            import msvcrt
            if os.fstat(stream.fileno()).st_size == 0:
                stream.write(b'\0')
                stream.flush()
            stream.seek(0)
            acquire = lambda: msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            release = lambda: (stream.seek(0), msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1))
        else:
            import fcntl
            acquire = lambda: fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            release = lambda: fcntl.flock(stream, fcntl.LOCK_UN)
        try:
            acquire()
        except OSError as exc:
            if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise
            raise RuntimeError('Ultra is being prepared by another WeCFU process. Retry after it finishes.') from exc
        try:
            yield
        finally:
            release()


# Use fixed-width Win32 fields so ABI layout can also be inspected off Windows.
_DWORD = ctypes.c_uint32
_SIZE = ctypes.c_size_t
_HANDLE = ctypes.c_void_p


class _MemoryCounters(ctypes.Structure):
    _fields_ = [('cb', _DWORD), ('PageFaultCount', _DWORD)] + [
        (name, _SIZE) for name in ('PeakWorkingSetSize', 'WorkingSetSize',
            'QuotaPeakPagedPoolUsage', 'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage',
            'QuotaNonPagedPoolUsage', 'PagefileUsage', 'PeakPagefileUsage')]


class _BasicLimits(ctypes.Structure):
    _fields_ = [('PerProcessUserTimeLimit', ctypes.c_int64), ('PerJobUserTimeLimit', ctypes.c_int64),
                ('LimitFlags', _DWORD), ('MinimumWorkingSetSize', _SIZE), ('MaximumWorkingSetSize', _SIZE),
                ('ActiveProcessLimit', _DWORD), ('Affinity', _SIZE), ('PriorityClass', _DWORD), ('SchedulingClass', _DWORD)]


class _IOCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in ('ReadOperationCount', 'WriteOperationCount',
        'OtherOperationCount', 'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount')]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [('BasicLimitInformation', _BasicLimits), ('IoInfo', _IOCounters)] + [
        (name, _SIZE) for name in ('ProcessMemoryLimit', 'JobMemoryLimit', 'PeakProcessMemoryUsed', 'PeakJobMemoryUsed')]


class _JobAccounting(ctypes.Structure):
    _fields_ = [(name, ctypes.c_int64) for name in ('TotalUserTime', 'TotalKernelTime',
        'ThisPeriodTotalUserTime', 'ThisPeriodTotalKernelTime')] + [
        (name, _DWORD) for name in ('TotalPageFaultCount', 'TotalProcesses', 'ActiveProcesses', 'TotalTerminatedProcesses')]


class _WindowsAPI:
    def __init__(self):
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.psapi = ctypes.WinDLL('psapi', use_last_error=True)
        signatures = {
            'CreateJobObjectW': ([ctypes.c_void_p, ctypes.c_wchar_p], _HANDLE),
            'SetInformationJobObject': ([_HANDLE, ctypes.c_int, ctypes.c_void_p, _DWORD], ctypes.c_int),
            'AssignProcessToJobObject': ([_HANDLE, _HANDLE], ctypes.c_int),
            'TerminateJobObject': ([_HANDLE, ctypes.c_uint], ctypes.c_int),
            'QueryInformationJobObject': ([_HANDLE, ctypes.c_int, ctypes.c_void_p, _DWORD, ctypes.c_void_p], ctypes.c_int),
            'CloseHandle': ([_HANDLE], ctypes.c_int),
            'GetCurrentProcess': ([], _HANDLE),
        }
        for name, (args, result) in signatures.items():
            function = getattr(self.kernel, name)
            function.argtypes, function.restype = args, result
        self.psapi.GetProcessMemoryInfo.argtypes = [_HANDLE, ctypes.POINTER(_MemoryCounters), _DWORD]
        self.psapi.GetProcessMemoryInfo.restype = ctypes.c_int

    @staticmethod
    def checked(ok):
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())
        return ok

    def create_job(self):
        handle = self.checked(self.kernel.CreateJobObjectW(None, None))
        limits = _ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        try:
            self.checked(self.kernel.SetInformationJobObject(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)))
        except BaseException:
            self.close(handle)
            raise
        return handle

    def assign(self, job, process):
        self.checked(self.kernel.AssignProcessToJobObject(job, int(process._handle)))

    def terminate(self, job):
        self.checked(self.kernel.TerminateJobObject(job, 1))

    def active(self, job):
        data = _JobAccounting()
        self.checked(self.kernel.QueryInformationJobObject(job, 1, ctypes.byref(data), ctypes.sizeof(data), None))
        return int(data.ActiveProcesses)

    def close(self, handle):
        self.checked(self.kernel.CloseHandle(handle))

    def memory(self, handle):
        data = _MemoryCounters()
        data.cb = ctypes.sizeof(data)
        self.checked(self.psapi.GetProcessMemoryInfo(handle, ctypes.byref(data), data.cb))
        return int(data.WorkingSetSize), int(data.PeakWorkingSetSize)

    def self_memory(self):
        return self.memory(self.kernel.GetCurrentProcess())


def _windows_api():
    return _WindowsAPI()


_OWNED = {}
_OWNED_LOCK = threading.RLock()
_WINDOWS_GATE = '''import os,runpy,sys
if os.read(sys.stdin.fileno(),1)!=b"G":sys.exit(125)
worker=os.path.abspath(sys.argv[1])
sys.argv=sys.argv[1:]
sys.path[0]=os.path.dirname(worker)
runpy.run_path(worker,run_name="__main__")
'''


def spawn_owned(command, **kwargs):
    """Spawn a direct Python worker. Windows gates script execution on Job ownership.

    The one-byte gate uses os.read, never a buffering reader: subsequent warm
    JSON requests remain intact. Neither a shell nor an exec-created PID is used.
    """
    if sys.platform != 'win32':
        desktop = os.environ.get('WECFU_DESKTOP_MANAGED') == '1'
        process = subprocess.Popen(command, **{**kwargs, 'start_new_session': not desktop})
        # Desktop workers share the shell-owned host group so forced shell
        # shutdown reaches them. Individual retirement must not kill that group.
        process._wecfu_desktop_group = desktop
        return process
    if (type(command) is not list or len(command) < 3 or command[1] != '-B'
            or any(type(arg) is not str or not arg for arg in command)):
        raise ValueError('Owned Windows worker requires [python, -B, script, ...]')
    if kwargs.get('stdin') not in (None, subprocess.PIPE):
        raise ValueError('Windows worker stdin is reserved for its ownership gate/protocol')
    if kwargs.get('text') or kwargs.get('universal_newlines') or kwargs.get('encoding'):
        raise ValueError('Windows worker protocol must be binary')
    if kwargs.get('creationflags', 0) or kwargs.get('shell'):
        raise ValueError('Windows worker process flags are owned by the supervisor')
    kwargs.pop('start_new_session', None)
    api = _windows_api()
    job = api.create_job()
    process = None
    try:
        process = subprocess.Popen([command[0], '-B', '-c', _WINDOWS_GATE, *command[2:]],
            **{**kwargs, 'stdin': subprocess.PIPE, 'bufsize': 0, 'creationflags': 0x08000000})  # CREATE_NO_WINDOW
        api.assign(job, process)
        with _OWNED_LOCK:
            if process.pid in _OWNED:
                raise RuntimeError('Owned worker PID collision')
            _OWNED[process.pid] = (process, api, job)
        if process.stdin.write(b'G') != 1:
            raise RuntimeError('Worker ownership gate write failed')
        process.stdin.flush()
        return process
    except BaseException:
        # Keep the original spawn/assignment error; cleanup paths are independent
        # so a failed Job call cannot strand the still-gated direct process.
        try:
            api.terminate(job)
        except OSError:
            pass
        try:
            if process is not None:
                try:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=4)
                finally:
                    for stream in (process.stdin, process.stdout, process.stderr):
                        if stream is not None:
                            try:
                                stream.close()
                            except OSError:
                                pass
        finally:
            try:
                api.close(job)  # KILL_ON_JOB_CLOSE is a second subtree safeguard.
            finally:
                if process is not None:
                    with _OWNED_LOCK:
                        _OWNED.pop(process.pid, None)
        raise


def stop_owned(process, timeout=4):
    """Retire only a process/job created by this application; wait before releasing ownership."""
    if sys.platform != 'win32':
        if process.poll() is None:
            try:
                if getattr(process, '_wecfu_desktop_group', False):
                    process.kill()
                else:
                    os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.wait(timeout=timeout)
        return
    with _OWNED_LOCK:
        owned = _OWNED.get(process.pid)
        if owned is None and getattr(process, '_wecfu_job_retired', False) and process.poll() is not None:
            return
        if owned is None or owned[0] is not process:
            raise RuntimeError('Cannot stop an unowned Windows process')
        _, api, job = owned
        deadline = time.monotonic() + timeout
        api.terminate(job)  # Also kills descendants after the direct child has exited.
        process.wait(timeout=max(0, deadline - time.monotonic()))
        while api.active(job):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired('owned worker job', timeout)
            time.sleep(min(.01, remaining))
        api.close(job)
        del _OWNED[process.pid]
        process._wecfu_job_retired = True


def sampled_rss(pid):
    if sys.platform == 'win32':
        with _OWNED_LOCK:
            owned = _OWNED.get(pid)
            if owned is None:
                raise RuntimeError('Cannot sample an unowned Windows process')
            process, api, _ = owned
            if process.poll() is not None:
                raise ProcessLookupError(pid)
            value, _ = api.memory(int(process._handle))
        if value <= 0:
            raise RuntimeError('Invalid Windows working-set sample')
        return value
    if sys.platform == 'linux':
        for line in Path(f'/proc/{pid}/status').read_text().splitlines():
            if line.startswith('VmRSS:'):
                return int(line.split()[1]) * 1024
        raise RuntimeError('Cannot sample local model memory')
    class TaskInfo(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in ('virtual_size', 'resident_size', 'total_user',
            'total_system', 'threads_user', 'threads_system')] + [(name, ctypes.c_int32) for name in (
            'policy', 'faults', 'pageins', 'cow_faults', 'messages_sent', 'messages_received', 'syscalls_mach',
            'syscalls_unix', 'csw', 'threadnum', 'numrunning', 'priority')]
    if sys.platform != 'darwin' or ctypes.sizeof(TaskInfo) != 96:
        raise RuntimeError('Unsupported local memory monitor')
    library = ctypes.CDLL('/usr/lib/libproc.dylib', use_errno=True)
    query = library.proc_pidinfo
    query.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
    query.restype = ctypes.c_int
    info = TaskInfo()
    ctypes.set_errno(0)
    if query(pid, 4, 0, ctypes.byref(info), ctypes.sizeof(info)) != ctypes.sizeof(info):
        number = ctypes.get_errno()
        if number == errno.ESRCH:
            raise ProcessLookupError(pid)
        raise OSError(number, 'Local model memory monitor became unavailable')
    if info.resident_size <= 0:
        raise RuntimeError('Invalid local model memory sample')
    return int(info.resident_size)


def self_peak_rss():
    if sys.platform == 'win32':
        _, peak = _windows_api().self_memory()
        if peak <= 0:
            raise RuntimeError('Invalid Windows peak working-set sample')
        return peak
    import resource
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * (1 if sys.platform == 'darwin' else 1024)
