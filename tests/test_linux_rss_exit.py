"""Synthetic /proc states and tiny own-child exits; no model imports."""
import errno
import sys
from pathlib import Path
from unittest import mock
import pytest
from wecfu.server.fusion_dino import process_monitor as monitor


@pytest.mark.parametrize('status',['State:\tR (running)\n','State:\tS (sleeping)\nVmRSS:\t0 kB\n'])
@pytest.mark.parametrize('platform,polls',[('linux',101),('darwin',11)])
def test_only_absent_or_zero_linux_rss_enters_exit_confirmation(status,platform,polls):
    instance=object.__new__(monitor.OwnChildRSS)
    instance.child=mock.Mock(pid=123,returncode=None)
    with mock.patch.object(monitor.sys,'platform','linux'),mock.patch.object(Path,'read_text',return_value=status):
        with pytest.raises(monitor.LinuxRSSUnavailable) as caught:instance.resident_bytes()
    assert caught.value.errno==errno.ESRCH
    with mock.patch.object(monitor.sys,'platform',platform):
        confirmed=monitor.resolve_exit_race(caught.value,lambda:True,1.,clock=lambda:0.,sleep=lambda _:None)
        assert confirmed['confirmed_exit'] and confirmed['wait4_polls']==1
        live=monitor.resolve_exit_race(caught.value,lambda:False,1.,clock=lambda:0.,sleep=lambda _:None)
    assert not live['confirmed_exit'] and live['wait4_polls']==polls


@pytest.mark.parametrize('status',['VmRSS:\tgarbage kB\n','VmRSS:\t-1 kB\n','VmRSS:\n'])
def test_malformed_rss_does_not_enter_exit_confirmation(status):
    instance=object.__new__(monitor.OwnChildRSS)
    instance.child=mock.Mock(pid=123,returncode=None)
    with mock.patch.object(monitor.sys,'platform','linux'),mock.patch.object(Path,'read_text',return_value=status):
        with pytest.raises((ValueError,IndexError)) as caught:instance.resident_bytes()
    reap=mock.Mock(return_value=True)
    result=monitor.resolve_exit_race(caught.value,reap,1.,clock=lambda:0.,sleep=lambda _:None)
    assert not result['confirmed_exit'];reap.assert_not_called()


@pytest.mark.parametrize('returncode,expected',[(0,'success'),(7,'child_failed')])
def test_confirmed_exit_still_requires_zero_code_and_authorized_work(returncode,expected):
    # The existing supervisor still owns and reaps a genuine scalar-only child.
    # At its first post-authorization sample, observe its stdout EOF without
    # reaping; only the supervisor's wait4 may establish the final exit status.
    original=monitor.OwnChildRSS.resident_bytes
    observed=[]
    def sample(instance):
        if instance.child.stdin.closed and not observed:
            import os,time
            until=time.monotonic()+1.
            while time.monotonic()<until:
                try:eof=os.read(instance.child.stdout.fileno(),1)==b''
                except BlockingIOError:eof=False
                if eof:
                    observed.append(True)
                    raise monitor.LinuxRSSUnavailable()
                time.sleep(.001)
            raise AssertionError('tiny fixture failed to exit')
        return original(instance)
    code=("import json,os,resource,sys,time;resource.setrlimit(resource.RLIMIT_CPU,(5,5));"
          "print(json.dumps({'kind':'ready','pid':os.getpid(),'cpu_limits':{'after':[5,5]}}),flush=True);"
          "assert sys.stdin.buffer.read(1)==b'G';time.sleep(.04);sys.exit("+str(returncode)+")")
    with mock.patch.object(monitor.OwnChildRSS,'resident_bytes',sample):
        report,_,_=monitor.supervise([sys.executable,'-c',code],rss_bytes=128*1024**2,
                                    wall_seconds=5,cpu_seconds=5,output_bytes=4096)
    assert observed and report['work_authorized']
    assert report['outcome']==expected and report['returncode']==returncode
    assert report['wait4_peak_resident_bytes']>0
    assert report['exit_race_checks'][-1]['confirmed_exit'] is True


def test_live_unavailable_sample_is_killed_not_accepted():
    original=monitor.OwnChildRSS.resident_bytes
    def sample(instance):
        if instance.child.stdin.closed:raise monitor.LinuxRSSUnavailable()
        return original(instance)
    code=("import json,os,resource,sys,time;resource.setrlimit(resource.RLIMIT_CPU,(5,5));"
          "print(json.dumps({'kind':'ready','pid':os.getpid(),'cpu_limits':{'after':[5,5]}}),flush=True);"
          "assert sys.stdin.buffer.read(1)==b'G';time.sleep(10)")
    with mock.patch.object(monitor.OwnChildRSS,'resident_bytes',sample):
        report,_,_=monitor.supervise([sys.executable,'-c',code],rss_bytes=128*1024**2,
                                    wall_seconds=5,cpu_seconds=5,output_bytes=4096)
    assert report['outcome']=='monitor_unavailable' and report['returncode']!=0
    assert not report['exit_race_checks'][-1]['confirmed_exit']
