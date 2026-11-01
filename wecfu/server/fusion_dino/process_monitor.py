"""Engineering-only bounded synthetic children; no model/checkpoint entry point.

Parent polls only its Popen child's Darwin resident size; wait4 captures that
child's kernel peak at exit. Polling is NOT an instantaneous RSS hard ceiling.
An unavailable monitor aborts before the child receives permission to work.
"""
import argparse
import ctypes
import errno
import hashlib
import json
import math
import os
from pathlib import Path
try:
    import resource
except ImportError:  # The core application can start on Windows; models cannot.
    resource = None
import selectors
import signal
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
MAX_RSS = 4 * 1024 ** 3
MAX_WALL = 900
MAX_CPU = 900
MAX_OUTPUT = 32 * 1024 ** 2
POLL_SECONDS = .01
MODES = {'normal', 'allocate', 'sleep', 'stdout', 'stderr', 'exit0', 'exit1', 'busy'}
EXIT_RACE_SECONDS = .05
EXIT_RACE_POLLS = 11
EXIT_RACE_POLL_SECONDS = .005


def require(ok, message):
    if not ok:
        raise ValueError(message)


class TaskInfo(ctypes.Structure):
    # Apple SDK sys/proc_info.h struct proc_taskinfo, six uint64 + twelve int32.
    _fields_ = [(name, ctypes.c_uint64) for name in (
        'virtual_size', 'resident_size', 'total_user', 'total_system', 'threads_user', 'threads_system')]
    _fields_ += [(name, ctypes.c_int32) for name in (
        'policy', 'faults', 'pageins', 'cow_faults', 'messages_sent', 'messages_received',
            'syscalls_mach', 'syscalls_unix', 'csw', 'threadnum', 'numrunning', 'priority')]


class LinuxRSSUnavailable(OSError):
    """Linux can release its address space before changing State to Z.

    This is only an invitation to the bounded same-child wait4 check, never
    evidence of successful exit. A still-live child remains a monitor failure.
    """
    def __init__(self):
        super().__init__(errno.ESRCH, 'own Linux child has no resident sample; confirm exit')


class OwnChildRSS:
    def __init__(self, child):
        require(sys.platform in ('darwin','linux') and isinstance(child, subprocess.Popen),
                'only our own Popen child on Darwin/Linux is supported')
        self.child = child
        if sys.platform == 'linux': return
        require(ctypes.sizeof(TaskInfo) == 96, 'unexpected proc_taskinfo ABI size')
        self.child = child
        self.library = ctypes.CDLL('/usr/lib/libproc.dylib', use_errno=True)
        self.call = self.library.proc_pidinfo
        self.call.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
        self.call.restype = ctypes.c_int

    def resident_bytes(self):
        require(self.child.returncode is None, 'do not query reaped/reused PID')
        if sys.platform == 'linux':
            try:
                lines=Path(f'/proc/{self.child.pid}/status').read_text().splitlines()
            except FileNotFoundError as exc:
                raise OSError(errno.ESRCH, 'own child exited') from exc
            for line in lines:
                if line.startswith('VmRSS:'):
                    value=int(line.split()[1])*1024
                    if value == 0:
                        raise LinuxRSSUnavailable()
                    require(value>0,'invalid Linux resident sample')
                    return value
            raise LinuxRSSUnavailable()
        info = TaskInfo()
        ctypes.set_errno(0)
        size = self.call(self.child.pid, 4, 0, ctypes.byref(info), ctypes.sizeof(info))
        if size != ctypes.sizeof(info):
            number = ctypes.get_errno()
            raise OSError(number, f'own-child proc_pidinfo returned {size}/96: {os.strerror(number)}')
        require(info.resident_size > 0, 'invalid resident-size sample')
        return int(info.resident_size)


def cpu_limit(requested):
    """Never raise inherited soft/hard CPU limits; RSS/AS APIs are not used."""
    require(resource is not None, 'model CPU limits require Darwin/Linux')
    before = resource.getrlimit(resource.RLIMIT_CPU)
    finite = [v for v in before if v != resource.RLIM_INFINITY]
    effective = min([requested] + finite)
    require(type(effective) is int and 0 < effective <= requested, 'inherited CPU budget cannot be honored')
    resource.setrlimit(resource.RLIMIT_CPU, (effective, effective))
    after = resource.getrlimit(resource.RLIMIT_CPU)
    require(after == (effective, effective), 'CPU hard limit failed')
    return {'before': list(before), 'after': list(after), 'requested': requested}


def resolve_exit_race(exc, reap, wall_deadline, *, clock=time.monotonic, sleep=time.sleep):
    """Only ESRCH may await a *confirmed* own-child exit, for a fixed short interval."""
    start = clock()
    record = {'errno': getattr(exc, 'errno', None), 'wait4_polls': 0,
              'confirmed_exit': False, 'elapsed_seconds': 0.0}
    if not isinstance(exc, OSError) or exc.errno != errno.ESRCH:
        return record
    deadline = min(wall_deadline, start + EXIT_RACE_SECONDS)
    for attempt in range(EXIT_RACE_POLLS):
        record['wait4_polls'] += 1
        if reap():
            record['confirmed_exit'] = True
            break
        now = clock()
        if now >= deadline or attempt + 1 == EXIT_RACE_POLLS:
            break
        sleep(min(EXIT_RACE_POLL_SECONDS, deadline - now))
    record['elapsed_seconds'] = clock() - start
    return record


def validate_limits(rss_bytes, wall_seconds, cpu_seconds, output_bytes):
    require(type(rss_bytes) is int and 0 < rss_bytes <= MAX_RSS, 'RSS limit range')
    require(type(wall_seconds) in (int, float) and math.isfinite(wall_seconds)
            and 0 < wall_seconds <= MAX_WALL, 'wall limit range')
    require(type(cpu_seconds) is int and 0 < cpu_seconds <= MAX_CPU, 'CPU limit range')
    require(type(output_bytes) is int and 0 < output_bytes <= MAX_OUTPUT, 'output cap range')


def supervise(command, *, rss_bytes=MAX_RSS, wall_seconds=MAX_WALL,
              cpu_seconds=MAX_CPU, output_bytes=MAX_OUTPUT, progress=None, parent_budget=None):
    """Supervise a new direct child with the reviewed CPU/readiness/G handshake.

    Caller owns command/source approval. No shell, existing PID, descendants,
    GPU monitor, checkpoint knowledge, permission fallback or automatic retry.
    """
    require(sys.platform in ('darwin','linux') and resource is not None,
            'local model supervision requires Darwin/Linux')
    validate_limits(rss_bytes, wall_seconds, cpu_seconds, output_bytes)
    require(type(command) is list and command and all(type(x) is str and x for x in command),
            'explicit nonempty argv required; no shell command')
    if parent_budget is not None: parent_budget.check()
    start = time.monotonic(); deadline = start + wall_seconds
    child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, close_fds=True, start_new_session=True)
    selector = selectors.DefaultSelector()
    buffers = {child.stdout: bytearray(), child.stderr: bytearray()}
    observed = retained = samples = peak = 0
    ready = None; authorized = False; outcome = None; error = None; usage = None
    races = []; progress_offset = 0

    def reap():
        nonlocal usage
        if child.returncode is not None:
            return True
        pid, status, info = os.wait4(child.pid, os.WNOHANG)
        if pid:
            require(pid == child.pid, 'unexpected reaped PID')
            child.returncode = os.waitstatus_to_exitcode(status); usage = info
            return True
        return False

    def kill(reason, exc=None):
        nonlocal outcome, error
        if outcome is None:
            outcome, error = reason, repr(exc) if exc is not None else None
        if not reap():
            try: os.kill(child.pid, signal.SIGKILL)
            except ProcessLookupError: pass

    def monitor_error(exc):
        # Other errno, malformed sample and ABI errors never enter the retry window.
        race = resolve_exit_race(exc, reap, deadline)
        if race['errno'] == errno.ESRCH:
            races.append(race)
        if not race['confirmed_exit']:
            kill('monitor_unavailable', exc)

    try:
        for stream in buffers:
            os.set_blocking(stream.fileno(), False); selector.register(stream, selectors.EVENT_READ)
        try:
            monitor = OwnChildRSS(child)
            peak = monitor.resident_bytes(); samples += 1
        except (OSError, ValueError) as exc:
            monitor_error(exc); monitor = None
        while True:
            if parent_budget is not None and outcome is None:
                try: parent_budget.check()
                except (ValueError, TimeoutError) as exc: kill('parent_budget', exc)
            done = reap()
            if time.monotonic() >= deadline:
                kill('wall_limit')
                # Do not await indefinitely an EOF held by an unexpected descendant.
                for key in list(selector.get_map().values()):
                    selector.unregister(key.fileobj)
            if monitor is not None and not done and outcome is None:
                try:
                    value = monitor.resident_bytes(); samples += 1; peak = max(peak, value)
                    if value > rss_bytes: kill('rss_limit')
                except (OSError, ValueError) as exc:
                    monitor_error(exc)
            done = reap()
            if progress is not None and outcome is None:
                try: progress.check(time.monotonic())
                except (ValueError, TimeoutError) as exc: kill('image_watchdog', exc)
            delay = min(POLL_SECONDS, max(0, deadline - time.monotonic())) if not done else 0
            for key, _ in selector.select(delay):
                stream = key.fileobj; chunk = os.read(stream.fileno(), 64 * 1024)
                if not chunk:
                    selector.unregister(stream); continue
                observed += len(chunk)
                take = min(len(chunk), max(0, output_bytes - retained))
                buffers[stream].extend(chunk[:take]); retained += take
                if observed > output_bytes: kill('output_limit')
            if progress is not None and outcome is None:
                try:
                    while True:
                        end = buffers[child.stderr].find(b'\n', progress_offset)
                        if end < 0: break
                        line = bytes(buffers[child.stderr][progress_offset:end]); progress_offset = end + 1
                        progress.line(line, time.monotonic())
                except (ValueError, TimeoutError) as exc: kill('image_watchdog', exc)
            if ready is None and b'\n' in buffers[child.stdout] and outcome is None:
                try:
                    line = bytes(buffers[child.stdout]).split(b'\n', 1)[0]
                    require(len(line) <= 4096, 'readiness size')
                    ready = json.loads(line); limits = ready['cpu_limits']['after']
                    require(ready['kind'] == 'ready' and ready['pid'] == child.pid and len(limits) == 2
                            and all(type(x) is int for x in limits)
                            and 0 < limits[0] == limits[1] <= cpu_seconds, 'CPU hard limit handshake invalid')
                    require(monitor is not None and samples > 0 and peak <= rss_bytes,
                            'RSS guard before work')
                    require(not reap(), 'child exited before work authorization')
                    child.stdin.write(b'G'); child.stdin.flush(); child.stdin.close(); authorized = True
                except (ValueError, KeyError, TypeError, BrokenPipeError) as exc:
                    kill('handshake_failure', exc)
            if reap() and not selector.get_map():
                break
        if progress is not None and outcome is None:
            try: progress.finish(time.monotonic())
            except (ValueError, TimeoutError) as exc: kill('incomplete_image_sequence', exc)
        final_peak = int(usage.ru_maxrss) * (1024 if sys.platform == 'linux' else 1) if usage is not None else None
        if outcome is None:
            if final_peak is None: outcome = 'peak_unavailable'
            elif final_peak > rss_bytes: outcome = 'rss_peak_exceeded_after_exit'
            elif time.monotonic() - start > wall_seconds: outcome = 'wall_limit_after_exit'
            elif not authorized or child.returncode != 0: outcome = 'child_failed'
            else: outcome = 'success'
        report = {'outcome': outcome, 'error': error, 'returncode': child.returncode,
                  'child_pid': child.pid, 'work_authorized': authorized, 'ready': ready,
                  'limits': {'rss_threshold_bytes': rss_bytes, 'wall_seconds': wall_seconds,
                             'cpu_seconds': cpu_seconds, 'combined_output_bytes': output_bytes},
                  'resident_samples': samples, 'sampled_peak_resident_bytes': peak,
                  'wait4_peak_resident_bytes': final_peak, 'elapsed_seconds': time.monotonic() - start,
                  'child_CPU_seconds': None if usage is None else usage.ru_utime + usage.ru_stime,
                  'output_bytes_observed': observed, 'output_bytes_retained': retained,
                  'exit_race_checks': races, 'instantaneous_RSS_hard_limit': False,
                  'sampling_overshoot_possible': True, 'descendant_or_GPU_resources_monitored': False}
        return report, bytes(buffers[child.stdout]), bytes(buffers[child.stderr])
    finally:
        if not reap():
            try: os.kill(child.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            _, status, _ = os.wait4(child.pid, 0); child.returncode = os.waitstatus_to_exitcode(status)
        selector.close()
        for stream in (child.stdin, child.stdout, child.stderr):
            if not stream.closed: stream.close()
