"""Bounded Windows-pipe adapters; synthetic bytes only, no models or pictures."""
import ctypes
import os
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from wecfu.platform_runtime import spawn_owned, stop_owned
from wecfu.server import sam_warm_pool as warm
from wecfu.server import sam_worker as worker


def test_reader_peek_path_handles_buffered_lines_without_select(monkeypatch):
    read_fd, write_fd = os.pipe()
    try:
        os.write(write_fd, b'one\ntwo\n')
        reader = worker.ProtocolReader(read_fd)
        values = iter([0, 8, None])
        reader.peek = lambda: next(values)
        monkeypatch.setattr(worker.select, 'select', lambda *a: pytest.fail('Windows selected an anonymous pipe'))
        assert reader.read(.2) == b'one'
        assert reader.read(.2) == b'two'
        assert reader.read(.2) is None
    finally:
        os.close(read_fd)
        os.close(write_fd)


@pytest.mark.parametrize('data,match', [(b'x' * 4096, 'protocol budget'), (b'partial', 'Incomplete')])
def test_reader_peek_path_rejects_unbounded_or_truncated_command(data, match):
    read_fd, write_fd = os.pipe()
    try:
        os.write(write_fd, data)
        reader = worker.ProtocolReader(read_fd)
        values = iter([len(data), None])
        reader.peek = lambda: next(values)
        with pytest.raises(RuntimeError, match=match):
            reader.read(.2)
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_reader_peek_idle_deadline_never_calls_blocking_read(monkeypatch):
    reader = worker.ProtocolReader(0)
    reader.peek = lambda: 0
    monkeypatch.setattr(os, 'read', lambda *a: pytest.fail('read without available bytes'))
    started = time.monotonic()
    assert reader.read(.025) is None
    assert time.monotonic() - started < .2


def test_windows_peek_uses_full_handle_binary_mode_and_eof_errors(monkeypatch):
    calls, binary = [], []
    handle = 2**40 + 7
    class Peek:
        fail = False
        def __call__(self, value, _buffer, _size, _read, available, _left):
            calls.append(value)
            available._obj.value = 37
            return not self.fail
    peek = Peek()
    monkeypatch.setitem(sys.modules, 'msvcrt', SimpleNamespace(
        get_osfhandle=lambda fd: handle, setmode=lambda fd, mode: binary.append((fd, mode))))
    monkeypatch.setattr(os, 'O_BINARY', 32768, raising=False)
    monkeypatch.setattr(ctypes, 'WinDLL', lambda *a, **k: SimpleNamespace(PeekNamedPipe=peek), raising=False)
    monkeypatch.setattr(ctypes, 'get_last_error', lambda: 109, raising=False)
    available = worker._windows_pipe_peeker(11)
    assert available() == 37 and calls == [handle] and binary == [(11, 32768)]
    assert len(peek.argtypes) == 6
    peek.fail = True
    assert available() is None
    monkeypatch.setattr(ctypes, 'get_last_error', lambda: 5, raising=False)
    with pytest.raises(OSError, match='Cannot inspect'):
        available()


def test_windows_native_stdout_handle_is_redirected_as_well_as_crt(monkeypatch):
    calls, descriptors = [], []
    class SetHandle:
        success = True
        def __call__(self, target, handle):
            calls.append((target, handle))
            return self.success
    function = SetHandle()
    monkeypatch.setattr(worker, 'WINDOWS_PIPES', True)
    monkeypatch.setattr(os, 'dup2', lambda source, target: descriptors.append((source, target)))
    monkeypatch.setitem(sys.modules, 'msvcrt', SimpleNamespace(get_osfhandle=lambda fd: 2**40 + fd))
    monkeypatch.setattr(ctypes, 'WinDLL', lambda *a, **k: SimpleNamespace(SetStdHandle=function), raising=False)
    monkeypatch.setattr(ctypes, 'get_last_error', lambda: 5, raising=False)
    worker._redirect_stdout_to_stderr()
    assert descriptors == [(sys.stderr.fileno(), sys.stdout.fileno())]
    assert calls == [(-11, 2**40 + sys.stderr.fileno())]
    function.success = False
    with pytest.raises(OSError, match='Cannot isolate'):
        worker._redirect_stdout_to_stderr()


def test_pipe_reader_queue_is_bounded_and_full_queue_retires_cleanly(tmp_path):
    script = tmp_path / 'flood.py'
    script.write_text("import os\nwhile True: os.write(1, b'x' * 4096)\n")
    process = spawn_owned([sys.executable, '-B', str(script)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
    transport = warm._ThreadedPipes(process)
    transport.start()
    try:
        until = time.monotonic() + 2
        while not transport.events.full() and time.monotonic() < until:
            time.sleep(.01)
        assert transport.events.full()
        assert transport.events.qsize() == warm.PIPE_QUEUE_ITEMS
        assert transport.events.maxsize * warm.MAX_PROTOCOL_BYTES == 65536
        assert transport.writes.maxsize == 1 and len(transport.threads) == 3
    finally:
        stop_owned(process)
        transport.close()
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()
    assert not any(t.is_alive() for t in transport.threads)
    assert transport.events.empty() and transport.writes.empty()


def test_thread_transport_rejects_oversized_command_before_queueing():
    transport = warm._ThreadedPipes(SimpleNamespace())
    with pytest.raises(warm.WarmWorkerError, match='cannot accept'):
        transport.send(b'x' * (warm.MAX_PROTOCOL_BYTES + 1))
    assert transport.writes.empty()
