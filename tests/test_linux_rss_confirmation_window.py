"""Bounded Linux exit confirmation with synthetic clocks; no model execution."""
import errno
import sys
from types import SimpleNamespace
from unittest import mock

import pytest

from wecfu.server.fusion_dino import process_monitor as monitor


class Clock:
    def __init__(self, now=0.0):
        self.now = now
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        assert 0 < seconds <= .005
        self.sleeps.append(seconds)
        self.now += seconds


def test_linux_rss_confirms_exit_at_150ms_without_extending_wall():
    clock = Clock()
    polls = []

    def reap():
        polls.append(clock())
        return clock() >= .150

    with mock.patch.object(monitor.sys, 'platform', 'linux'):
        result = monitor.resolve_exit_race(
            monitor.LinuxRSSUnavailable(), reap, .8,
            clock=clock, sleep=clock.sleep,
        )
    assert result['confirmed_exit']
    assert .150 <= result['elapsed_seconds'] <= .5
    assert 1 < len(polls) <= 101
    assert max(polls) < .8


@pytest.mark.parametrize('platform,error', [
    ('linux', OSError(errno.ESRCH, 'gone')),
    ('darwin', OSError(errno.ESRCH, 'gone')),
    ('darwin', monitor.LinuxRSSUnavailable()),
])
def test_other_esrch_and_darwin_keep_50ms_window(platform, error):
    clock = Clock()
    with mock.patch.object(monitor.sys, 'platform', platform):
        result = monitor.resolve_exit_race(
            error, lambda: clock() >= .150, 1., clock=clock, sleep=clock.sleep,
        )
    assert not result['confirmed_exit']
    assert result['elapsed_seconds'] <= .05
    assert result['wait4_polls'] <= 11


@pytest.mark.parametrize('deadline,maximum', [(1., .5), (.02, .02)])
def test_linux_live_child_stays_failed_and_respects_shorter_wall(deadline, maximum):
    clock = Clock()
    with mock.patch.object(monitor.sys, 'platform', 'linux'):
        result = monitor.resolve_exit_race(
            monitor.LinuxRSSUnavailable(), lambda: clock() >= .6,
            deadline, clock=clock, sleep=clock.sleep,
        )
    assert not result['confirmed_exit']
    assert result['elapsed_seconds'] == pytest.approx(maximum)
    assert result['elapsed_seconds'] <= deadline
    assert result['wait4_polls'] <= 101


@pytest.mark.parametrize('error,window', [
    (monitor.LinuxRSSUnavailable(), .5), (OSError(errno.ESRCH, 'gone'), .05),
])
def test_sleep_crossing_deadline_cannot_confirm_exit(error, window):
    clock = Clock()
    polls = []

    def reap():
        polls.append(clock())
        if len(polls) == 1:
            clock.now = window - .01
            return False
        return True

    def oversleep(seconds):
        assert 0 < seconds <= .005
        assert clock() == pytest.approx(window - .01)
        clock.now = window + .1

    with mock.patch.object(monitor.sys, 'platform', 'linux'):
        result = monitor.resolve_exit_race(
            error, reap, 1., clock=clock, sleep=oversleep,
        )
    assert not result['confirmed_exit']
    assert result['wait4_polls'] == len(polls) == 1


@pytest.mark.parametrize('error,window', [
    (monitor.LinuxRSSUnavailable(), .5), (OSError(errno.ESRCH, 'gone'), .05),
])
@pytest.mark.parametrize('delay,confirmed', [(0., True), (.1, False)])
def test_reap_must_finish_no_later_than_deadline(error, window, delay, confirmed):
    clock = Clock()

    def reap():
        clock.now = window + delay
        return True

    with mock.patch.object(monitor.sys, 'platform', 'linux'):
        result = monitor.resolve_exit_race(
            error, reap, 1., clock=clock, sleep=clock.sleep,
        )
    assert result['confirmed_exit'] is confirmed
    assert result['wait4_polls'] == 1
    assert not clock.sleeps


@pytest.mark.parametrize('deadline', [.9, 1.])
def test_expired_wall_does_not_even_poll_or_sleep(deadline):
    clock = Clock(1.)
    reap = mock.Mock(return_value=True)
    with mock.patch.object(monitor.sys, 'platform', 'linux'):
        result = monitor.resolve_exit_race(
            monitor.LinuxRSSUnavailable(), reap, deadline,
            clock=clock, sleep=clock.sleep,
        )
    assert not result['confirmed_exit'] and result['wait4_polls'] == 0
    reap.assert_not_called()
    assert not clock.sleeps


def test_linux_frozen_clock_still_has_hard_101_poll_limit():
    reap = mock.Mock(return_value=False)
    sleep = mock.Mock()
    with mock.patch.object(monitor.sys, 'platform', 'linux'):
        result = monitor.resolve_exit_race(
            monitor.LinuxRSSUnavailable(), reap, 1., clock=lambda: 0., sleep=sleep,
        )
    assert not result['confirmed_exit']
    assert result['wait4_polls'] == reap.call_count == 101
    assert sleep.call_count == 100
    assert all(call.args == (.005,) for call in sleep.call_args_list)


@pytest.mark.parametrize('error', [PermissionError(errno.EACCES, 'denied'), ValueError('bad RSS')])
def test_permission_and_malformed_samples_never_poll(error):
    reap, sleep = mock.Mock(), mock.Mock()
    with mock.patch.object(monitor.sys, 'platform', 'linux'):
        result = monitor.resolve_exit_race(error, reap, 1., clock=lambda: 0., sleep=sleep)
    assert not result['confirmed_exit']
    reap.assert_not_called()
    sleep.assert_not_called()


@pytest.mark.skipif(sys.platform not in ('darwin', 'linux'), reason='own-child wait4 requires POSIX')
@pytest.mark.parametrize('case,expected', [
    ('nonzero', 'child_failed'),
    ('unauthorized', 'child_failed'),
    ('peak_exceeded', 'rss_peak_exceeded_after_exit'),
    ('peak_missing', 'peak_unavailable'),
])
def test_final_acceptance_guards_remain_fail_closed(case, expected):
    rss_limit = 128 * 1024 ** 2
    original_wait4 = monitor.os.wait4

    def wait4(pid, flags):
        child_pid, status, usage = original_wait4(pid, flags)
        if child_pid and case == 'peak_exceeded':
            scale = 1024 if sys.platform == 'linux' else 1
            usage = SimpleNamespace(ru_maxrss=rss_limit // scale + 1,
                                    ru_utime=usage.ru_utime, ru_stime=usage.ru_stime)
        elif child_pid and case == 'peak_missing':
            usage = None
        return child_pid, status, usage

    code = 'import sys;sys.exit(0)' if case == 'unauthorized' else (
        "import json,os,resource,sys;resource.setrlimit(resource.RLIMIT_CPU,(5,5));"
        "print(json.dumps({'kind':'ready','pid':os.getpid(),'cpu_limits':{'after':[5,5]}}),flush=True);"
        "assert sys.stdin.buffer.read(1)==b'G';sys.exit(" + ('7' if case == 'nonzero' else '0') + ')'
    )
    with mock.patch.object(monitor.os, 'wait4', wait4), \
            mock.patch.object(monitor.OwnChildRSS, 'resident_bytes', return_value=1024 ** 2):
        report, _, _ = monitor.supervise(
            [sys.executable, '-c', code], rss_bytes=rss_limit,
            wall_seconds=5, cpu_seconds=5, output_bytes=4096,
        )
    assert report['outcome'] == expected
    assert report['work_authorized'] is (case != 'unauthorized')
