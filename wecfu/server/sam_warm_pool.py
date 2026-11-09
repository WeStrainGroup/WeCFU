"""Opt-in bounded SAM worker transport; stdlib only, never caches image results.

One process-wide lock serializes the CV/infer pair across provider instances.
All failures retire both children; a failed request is never replayed.
"""
from __future__ import annotations

import atexit
import json
import os
from pathlib import Path
import queue
import selectors
import subprocess
import threading
import time
from uuid import uuid4

from wecfu.platform_runtime import spawn_owned

IDLE_SECONDS = 90.0
MAX_REQUESTS = 32
MAX_PROTOCOL_BYTES = 4096
MAX_LOG_BYTES = 8 * 1024**2
WINDOWS_PIPES = os.name == 'nt'
PIPE_QUEUE_ITEMS = 16


class WarmWorkerError(RuntimeError):
    pass


class _PipeWrite:
    def __init__(self, data):
        self.data = data
        self.done = threading.Event()
        self.error = None


class _ThreadedPipes:
    """Windows anonymous pipes cannot be selected; bound every queued byte.

    A fixed pair of readers and one writer belong to a single child process.
    They only transport protocol/log bytes, never decoded images or results.
    The owner must terminate the child before joining blocked pipe readers.
    """
    def __init__(self, process):
        self.process = process
        self.events = queue.Queue(maxsize=PIPE_QUEUE_ITEMS)
        self.writes = queue.Queue(maxsize=1)
        self.stopping = threading.Event()
        self.threads = []
        self.current = None

    def _publish(self, channel, value):
        while not self.stopping.is_set():
            try:
                self.events.put((channel, value), timeout=.05)
                return
            except queue.Full:
                pass

    def _read(self, channel, stream):
        try:
            while not self.stopping.is_set():
                data = os.read(stream.fileno(), MAX_PROTOCOL_BYTES)
                self._publish(channel, data)
                if not data:
                    return
        except OSError as exc:
            self._publish(channel, exc)

    def _write(self):
        while not self.stopping.is_set():
            try:
                job = self.writes.get(timeout=.05)
            except queue.Empty:
                continue
            try:
                sent = 0
                while sent < len(job.data):
                    if self.stopping.is_set():
                        raise OSError('Warm SAM pipe is closing')
                    size = os.write(self.process.stdin.fileno(), job.data[sent:])
                    if not size:
                        raise OSError('Warm SAM pipe accepted no bytes')
                    sent += size
            except OSError as exc:
                job.error = exc
            finally:
                job.data = b''
                job.done.set()

    def start(self):
        for channel in ('stdout', 'stderr'):
            thread = threading.Thread(target=self._read,
                args=(channel, getattr(self.process, channel)),
                name=f'wecfu-sam-{self.process.pid}-{channel}', daemon=True)
            self.threads.append(thread)
            thread.start()
        thread = threading.Thread(target=self._write,
            name=f'wecfu-sam-{self.process.pid}-stdin', daemon=True)
        self.threads.append(thread)
        thread.start()

    def send(self, data):
        if (self.stopping.is_set() or len(data) > MAX_PROTOCOL_BYTES or
                (self.current is not None and not self.current.done.is_set())):
            raise WarmWorkerError('Warm SAM pipe cannot accept another command')
        job = _PipeWrite(data)
        self.current = job
        try:
            self.writes.put_nowait(job)
        except queue.Full as exc:
            raise WarmWorkerError('Warm SAM command queue is full') from exc
        return job

    def close(self):
        self.stopping.set()
        until = time.monotonic() + 1.0
        for thread in self.threads:
            if thread.ident is not None:
                thread.join(max(0.0, until - time.monotonic()))
        if any(thread.is_alive() for thread in self.threads):
            raise WarmWorkerError('Warm SAM pipe threads could not be stopped')
        self.current = None
        for pending in (self.events, self.writes):
            while True:
                try:
                    pending.get_nowait()
                except queue.Empty:
                    break


class WarmSamPool:
    def __init__(self, *, idle_seconds=IDLE_SECONDS, max_requests=MAX_REQUESTS):
        self.lock = threading.Lock()
        self.children = {}
        self.signature = None
        self.last_used = None
        self.idle_seconds = idle_seconds
        self.max_requests = max_requests
        self._closed = False
        self._reaper = None
        self._stop = None

    def _close_locked(self):
        errors = []
        failed = {}
        for role, child in self.children.items():
            process = child['process']
            try:
                if not child.get('stopped'):
                    self._stop(process)
                    child['stopped'] = True
                if child.get('transport') is not None:
                    child['transport'].close()
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream:
                        stream.close()
            except Exception as exc:
                errors.append(exc)
                failed[role] = child
        # Retain handles whose termination was not confirmed, so shutdown or
        # atexit can retry cleanup; never spawn a replacement in this state.
        self.children = failed
        self.signature = None
        self.last_used = None
        if errors:
            self._closed = True
            raise WarmWorkerError('Warm SAM workers could not be stopped') from errors[0]

    def close(self):
        with self.lock:
            self._closed = True
            self._close_locked()

    def shutdown(self):
        """Retire resident workers when an ASGI app stops, without a new inference."""
        with self.lock:
            self._close_locked()

    def _ensure_reaper(self):
        if self._reaper is not None:
            return
        def reap():
            while not self._closed:
                time.sleep(min(1.0, self.idle_seconds))
                if not self.lock.acquire(blocking=False):
                    continue
                try:
                    if (self.children and self.last_used is not None
                            and time.monotonic() - self.last_used >= self.idle_seconds):
                        self._close_locked()
                except Exception:
                    # A failed reap must never silently reuse the old process.
                    self._closed = True
                finally:
                    self.lock.release()
        self._reaper = threading.Thread(target=reap, name='wecfu-sam-idle', daemon=True)
        self._reaper.start()

    def _spawn(self, role, executable, worker, repo, env):
        process = spawn_owned([str(executable), '-B', str(worker), '--serve', role],
            cwd=repo, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, bufsize=0)
        child = {'process': process, 'commands': 0, 'log_bytes': 0,
                 'output_bytes': 0, 'buffer': bytearray()}
        self.children[role] = child  # Register before setup so all failures are cleaned up.
        if WINDOWS_PIPES:
            child['transport'] = _ThreadedPipes(process)
            child['transport'].start()
        else:
            for stream in (process.stdin, process.stdout, process.stderr):
                os.set_blocking(stream.fileno(), False)
        return child

    @staticmethod
    def _deadline(deadline):
        if time.monotonic() >= deadline:
            raise WarmWorkerError('Local model preview exceeded 120 seconds')

    def _budget(self, folder, deadline, sample_rss, rss_limit, max_output, *, completed_role=None):
        self._deadline(deadline)
        total = 0
        for role, child in self.children.items():
            process = child['process']
            if process.poll() is not None:
                if (role == completed_role and child['commands'] + 1 == self.max_requests
                        and process.returncode == 0):
                    continue
                raise WarmWorkerError('Warm SAM worker exited; no request was retried')
            try:
                total += sample_rss(process.pid)
            except Exception as exc:
                raise WarmWorkerError('Warm SAM memory monitor became unavailable') from exc
        if total > rss_limit:
            raise WarmWorkerError('Local model preview exceeded the combined 4 GiB memory budget')
        for path in folder.iterdir():
            if path.is_file() and path.suffix in {'.json', '.log'} and path.stat().st_size > max_output:
                raise WarmWorkerError('Local model preview output exceeded its storage budget')
        return total

    def _exchange(self, role, stage, folder, deadline, sample_rss, rss_limit, max_output):
        token = uuid4().hex
        request = json.dumps({'id': token, 'folder': str(folder.resolve()), 'stage': stage},
                             separators=(',', ':')).encode() + b'\n'
        if len(request) > MAX_PROTOCOL_BYTES:
            raise WarmWorkerError('Warm SAM request exceeds protocol budget')
        active = self.children[role]
        if active.get('transport') is not None:
            return self._exchange_threaded(role, stage, folder, deadline, sample_rss,
                                           rss_limit, max_output, token, request)
        sent, reply, peak = 0, None, 0
        with selectors.DefaultSelector() as selector, (folder / (stage + '.log')).open('xb') as log:
            selector.register(active['process'].stdin, selectors.EVENT_WRITE, (role, 'stdin'))
            for child_role, child in self.children.items():
                selector.register(child['process'].stdout, selectors.EVENT_READ, (child_role, 'stdout'))
                selector.register(child['process'].stderr, selectors.EVENT_READ, (child_role, 'stderr'))
            while reply is None:
                peak = max(peak, self._budget(folder, deadline, sample_rss, rss_limit, max_output))
                for key, _ in selector.select(min(.05, max(0.0, deadline - time.monotonic()))):
                    child_role, channel = key.data
                    child = self.children[child_role]
                    if channel == 'stdin':
                        try:
                            sent += os.write(key.fileobj.fileno(), request[sent:])
                        except BlockingIOError:
                            continue
                        if sent == len(request):
                            selector.unregister(key.fileobj)
                        continue
                    try:
                        data = os.read(key.fileobj.fileno(), MAX_PROTOCOL_BYTES)
                    except BlockingIOError:
                        continue
                    if not data:
                        if reply is not None and child_role == role and child['commands'] + 1 == self.max_requests:
                            continue
                        raise WarmWorkerError('Warm SAM worker closed its output; no request was retried')
                    reply = self._consume_output(child_role, channel, data, role,
                        token, sent == len(request), reply, log)
            peak = max(peak, self._budget(folder, deadline, sample_rss, rss_limit, max_output,
                                          completed_role=role))
        active['commands'] += 1
        return peak

    def _consume_output(self, child_role, channel, data, role, token, sent, reply, log):
        """Identical framing and storage checks for both pipe transports."""
        child = self.children[child_role]
        if channel == 'stderr':
            child['log_bytes'] += len(data)
            if child['log_bytes'] > MAX_LOG_BYTES:
                raise WarmWorkerError('Warm SAM worker log exceeded its storage budget')
            log.write(data)
            return reply
        child['output_bytes'] += len(data)
        if child['output_bytes'] > MAX_PROTOCOL_BYTES * self.max_requests:
            raise WarmWorkerError('Warm SAM worker protocol output exceeded its storage budget')
        child['buffer'].extend(data)
        if len(child['buffer']) > MAX_PROTOCOL_BYTES:
            raise WarmWorkerError('Warm SAM response exceeds protocol budget')
        if child_role != role:
            raise WarmWorkerError('Unexpected output from idle warm SAM worker')
        if b'\n' not in child['buffer']:
            return reply
        line, remainder = bytes(child['buffer']).split(b'\n', 1)
        child['buffer'].clear()
        if remainder or not sent or reply is not None:
            raise WarmWorkerError('Unexpected extra warm SAM protocol output')
        try:
            reply = json.loads(line)
        except (ValueError, UnicodeError) as exc:
            raise WarmWorkerError('Malformed warm SAM response') from exc
        if (type(reply) is not dict or reply.get('id') != token
                or type(reply.get('ok')) is not bool
                or set(reply) != ({'id', 'ok'} if reply.get('ok') else {'id', 'ok', 'error'})):
            raise WarmWorkerError('Warm SAM response does not match its request')
        if not reply['ok']:
            error = reply.get('error')
            if not isinstance(error, str):
                raise WarmWorkerError('Malformed warm SAM failure response')
            raise WarmWorkerError('Warm SAM worker failed: ' + error[:768])
        return reply

    def _exchange_threaded(self, role, stage, folder, deadline, sample_rss,
                           rss_limit, max_output, token, request):
        active = self.children[role]
        job = active['transport'].send(request)
        reply, peak = None, 0
        with (folder / (stage + '.log')).open('xb') as log:
            while reply is None:
                peak = max(peak, self._budget(folder, deadline, sample_rss, rss_limit, max_output))
                # A reader can receive a reply just before the writer returns
                # from its final OS write. Do not interpret it as an early reply.
                if job.done.is_set():
                    if job.error is not None:
                        raise WarmWorkerError('Warm SAM pipe write failed; no request was retried') from job.error
                    for child_role, child in self.children.items():
                        events = child['transport'].events
                        for _ in range(PIPE_QUEUE_ITEMS):
                            try:
                                channel, data = events.get_nowait()
                            except queue.Empty:
                                break
                            if isinstance(data, OSError):
                                raise WarmWorkerError('Warm SAM pipe read failed; no request was retried') from data
                            if not data:
                                raise WarmWorkerError('Warm SAM worker closed its output; no request was retried')
                            reply = self._consume_output(child_role, channel, data,
                                role, token, True, reply, log)
                if reply is None:
                    time.sleep(min(.01, max(0.0, deadline - time.monotonic())))
            peak = max(peak, self._budget(folder, deadline, sample_rss, rss_limit, max_output,
                                         completed_role=role))
        active['commands'] += 1
        return peak

    def run(self, *, folder, deadline, env, cv_python, sam_python, worker, repo,
            verify_pins, sample_rss, stop_process, rss_limit, max_output, validate_result=lambda: None):
        """Run exactly once; queueing, pin checks and all three stages share a deadline."""
        started = time.monotonic()
        remaining = deadline - started
        if remaining <= 0 or not self.lock.acquire(timeout=max(0.0, remaining)):
            raise WarmWorkerError('Local model preview exceeded 120 seconds while queued')
        timings = {'queue_seconds': time.monotonic() - started, 'mode': 'warm_worker'}
        try:
            self._deadline(deadline)
            if self._closed:
                raise WarmWorkerError('Warm SAM worker pool is closed')
            self._stop = stop_process
            pin_started = time.monotonic()
            pins = verify_pins()
            timings['pin_seconds'] = time.monotonic() - pin_started
            self._deadline(deadline)
            # Expected lifecycle retirement is allowed before a new request;
            # unexpected death is a failed request, never an implicit retry.
            if self.children and (pins != self.signature or
                    time.monotonic() - self.last_used >= self.idle_seconds or
                    any(c['commands'] + (2 if role == 'cv' else 1) >= self.max_requests
                        for role, c in self.children.items())):
                self._close_locked()
            if self.children and any(c['process'].poll() is not None for c in self.children.values()):
                raise WarmWorkerError('Warm SAM worker exited between requests; no request was retried')
            timings['worker_reused'] = bool(self.children)
            timings['worker_started'] = {'prepare': not self.children, 'infer': not self.children, 'finish': False}
            if not self.children:
                self.signature = pins
                self._spawn('cv', cv_python, worker, repo, env)
                self._spawn('infer', sam_python, worker, repo, env)
            self._ensure_reaper()
            peaks = []
            for role, stage in (('cv', 'prepare'), ('infer', 'infer'), ('cv', 'finish')):
                stage_started = time.monotonic()
                peaks.append(self._exchange(role, stage, folder, deadline, sample_rss, rss_limit, max_output))
                timings[stage + '_seconds'] = time.monotonic() - stage_started
            if verify_pins() != pins:
                raise WarmWorkerError('Warm SAM runtime pins changed during inference')
            validate_result()
            self._deadline(deadline)
            self.last_used = time.monotonic()
            timings['sampled_peak_combined_rss_bytes'] = max(peaks, default=0)
            timings['worker_seconds'] = self.last_used - started
            # Leave room below the child's own cap so a flushed final response
            # never races its expected process exit at the protocol boundary.
            if any(c['commands'] + (2 if role == 'cv' else 1) >= self.max_requests
                   for role, c in self.children.items()):
                self._close_locked()
            self._deadline(deadline)
            return timings
        except Exception as exc:
            try:
                self._close_locked()
            except Exception as cleanup_error:
                exc.add_note('Worker retirement also failed: ' + str(cleanup_error))
            raise
        finally:
            self.lock.release()


POOL = WarmSamPool()
atexit.register(POOL.close)
