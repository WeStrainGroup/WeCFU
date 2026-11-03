"""Synthetic transport/lifecycle tests. No Torch, CV, weights or real pictures."""
import json
import os
from pathlib import Path
import signal
import sys
import threading
import time

import pytest

from wecfu.server import sam_warm_pool as warm


FAKE = r'''
import json, os, sys, time
from pathlib import Path
role = sys.argv[-1]
for line in sys.stdin:
    request = json.loads(line)
    folder = Path(request['folder'])
    with (folder/'trace.jsonl').open('a') as out:
        out.write(json.dumps({'pid':os.getpid(),'role':role,'stage':request['stage'],'time':time.monotonic()})+'\n')
    mode = os.environ.get('FAKE_MODE', '') if request['stage'] == 'infer' else ''
    if mode == 'death': os._exit(7)
    if mode == 'timeout': time.sleep(2)
    if mode == 'slow': time.sleep(.08)
    if mode == 'large': print('x'*5000, flush=True); continue
    if mode == 'malformed': print('not json', flush=True); continue
    if mode == 'log': print('x'*4096, file=sys.stderr, flush=True)
    if mode == 'file': (folder/'huge.json').write_bytes(b'x'*2048)
    result = {'id': request['id'], 'ok':True}
    if mode == 'wrong_id': result['id'] = 'wrong'
    if mode == 'failure': result = {'id':request['id'],'ok':False,'error':'synthetic failure'}
    if mode == 'extra': print(json.dumps(result)+'\n'+json.dumps(result), flush=True); continue
    print(json.dumps(result), flush=True)
'''


def stop(process):
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait(timeout=2)


@pytest.fixture
def harness(tmp_path):
    worker = tmp_path/'fake_worker.py'; worker.write_text(FAKE)
    pool = warm.WarmSamPool()
    sequence = 0
    def run(*, mode='', pins='same', timeout=3, **changes):
        nonlocal sequence
        sequence += 1
        folder = tmp_path/str(sequence); folder.mkdir()
        params = dict(folder=folder, deadline=time.monotonic()+timeout,
            env={**os.environ,'FAKE_MODE':mode}, cv_python=Path(sys.executable),
            sam_python=Path(sys.executable), worker=worker, repo=tmp_path,
            verify_pins=lambda:pins, sample_rss=lambda pid:100,
            stop_process=stop, rss_limit=1000, max_output=1024*1024)
        params.update(changes)
        return pool.run(**params), folder
    yield pool, run
    pool.close()


def pids(pool):
    return {role:child['process'] for role,child in pool.children.items()}


def test_one_pair_reused_three_stages_new_scratch_each_request(harness):
    pool,run=harness
    first,a=run(); original=pids(pool); second,b=run()
    assert first['worker_reused'] is False and second['worker_reused'] is True
    assert first['worker_started']=={'prepare':True,'infer':True,'finish':False}
    assert second['worker_started']=={'prepare':False,'infer':False,'finish':False}
    assert pids(pool)==original
    for folder in (a,b):
        trace=[json.loads(row) for row in (folder/'trace.jsonl').read_text().splitlines()]
        assert [row['stage'] for row in trace]==['prepare','infer','finish']
        assert trace[0]['pid']==trace[2]['pid']!=trace[1]['pid']
    assert first['sampled_peak_combined_rss_bytes']==200


@pytest.mark.parametrize('mode,match',[
    ('death','exited|closed'),('timeout','exceeded'),('large','protocol budget'),
    ('malformed','Malformed'),('wrong_id','does not match'),('failure','synthetic failure'),
    ('extra','extra'),('file','storage budget'),('log','log exceeded'),
])
def test_protocol_deadline_and_storage_errors_retire_both_without_retry(harness,monkeypatch,mode,match):
    pool,run=harness
    if mode=='log':monkeypatch.setattr(warm,'MAX_LOG_BYTES',128)
    captured=[]
    original_spawn=pool._spawn
    def capture(*args):
        child=original_spawn(*args);captured.append(child['process']);return child
    monkeypatch.setattr(pool,'_spawn',capture)
    with pytest.raises(warm.WarmWorkerError,match=match):
        run(mode=mode,timeout=.15 if mode=='timeout' else 3,max_output=1024 if mode=='file' else 1024*1024)
    assert len(captured)==2 and all(p.poll() is not None for p in captured)
    assert pool.children=={}


def test_combined_rss_not_individual_budget(harness):
    pool,run=harness
    with pytest.raises(warm.WarmWorkerError,match='combined 4 GiB'):
        run(rss_limit=150)
    assert pool.children=={}


def test_queue_wait_uses_the_same_deadline_without_starting_process(harness):
    pool,run=harness
    pool.lock.acquire()
    try:
        with pytest.raises(warm.WarmWorkerError,match='queued'):
            run(timeout=.02)
    finally:pool.lock.release()
    assert pool.children=={}


def test_two_calls_are_serialized_and_report_queue_time(harness):
    pool,run=harness; results=[];errors=[]
    def invoke():
        try:results.append(run(mode='slow'))
        except Exception as exc:errors.append(exc)
    a=threading.Thread(target=invoke);b=threading.Thread(target=invoke)
    a.start();time.sleep(.02);b.start();a.join(4);b.join(4)
    assert not errors and len(results)==2
    assert sorted(result[0]['worker_reused'] for result in results)==[False,True]
    assert max(result[0]['queue_seconds'] for result in results)>.04


def test_pin_change_retires_old_pair_before_fresh_start(harness):
    pool,run=harness
    run(pins='one');old=pids(pool);details,_=run(pins='two')
    assert details['worker_reused'] is False
    assert all(p.poll() is not None for p in old.values())
    assert set(p.pid for p in old.values()).isdisjoint(p.pid for p in pids(pool).values())


def test_pin_verification_failure_retires_pair_without_new_process(harness):
    pool,run=harness
    run();old=pids(pool)
    def bad():raise ValueError('synthetic changed pin')
    with pytest.raises(ValueError,match='changed pin'):run(verify_pins=bad)
    assert pool.children=={} and all(p.poll() is not None for p in old.values())


def test_post_request_pin_change_or_invalid_result_retires_pair(harness):
    pool,run=harness
    values=iter(['one','two'])
    with pytest.raises(warm.WarmWorkerError,match='pins changed'):run(verify_pins=lambda:next(values))
    assert pool.children=={}
    def bad_result():raise ValueError('invalid provenance')
    with pytest.raises(ValueError,match='invalid provenance'):run(validate_result=bad_result)
    assert pool.children=={}


def test_unexpected_death_between_requests_is_not_replayed(harness):
    pool,run=harness
    run();old=pids(pool);stop(old['infer'])
    with pytest.raises(warm.WarmWorkerError,match='between requests'):run()
    assert pool.children=={} and all(p.poll() is not None for p in old.values())


def test_idle_and_explicit_shutdown_release_both_processes(harness):
    pool,run=harness;pool.idle_seconds=.05
    run();old=pids(pool)
    until=time.monotonic()+1
    while pool.children and time.monotonic()<until:time.sleep(.01)
    assert pool.children=={} and all(p.poll() is not None for p in old.values())
    run();old=pids(pool);pool.shutdown()
    assert pool.children=={} and all(p.poll() is not None for p in old.values())
    details,_=run();assert details['worker_reused'] is False


def test_recycle_before_protocol_limit_avoids_flushed_reply_exit_race(harness):
    pool,run=harness;pool.max_requests=6
    run();old=pids(pool)
    details,_=run();assert details['worker_reused'] is True
    assert pool.children=={} and all(p.poll() is not None for p in old.values())
    details,_=run();assert details['worker_reused'] is False


def test_unconfirmed_stop_permanently_closes_pool(harness):
    pool,run=harness
    run();old=pids(pool)
    def failed(process):stop(process);raise RuntimeError('synthetic stop failure')
    with pytest.raises(warm.WarmWorkerError,match='could not be stopped'):
        run(pins='new',stop_process=failed)
    assert pool._closed and all(p.poll() is not None for p in old.values())
    with pytest.raises(warm.WarmWorkerError,match='closed'):run()
    # Subsequent explicit cleanup may confirm termination, but cannot reopen
    # a pool whose earlier stop was unconfirmed.
    pool._stop=stop;pool.shutdown()
    assert pool.children=={} and pool._closed
