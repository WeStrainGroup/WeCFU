import json
from io import StringIO
from unittest.mock import patch

import pytest

from wecfu.server import runtime_diagnostics as diagnostics


def example(**changes):
    return dict(diagnostic_id='a'*32,phase='fusion-dino',error_type='ValueError',
                message='single-image resource/runtime failure; no prediction success',
                details={},log_tails={}) | changes


def test_safe_summary_reports_worker_cause_and_numeric_resource():
    value=example(log_tails={
        'dino/logs.json':{'tail_utf8':json.dumps({'stdout':'', 'stderr':
            'Traceback:\n  File "/private/person/photo.png", line 3\n'
            'RuntimeError: local DINO: network/subprocess/other photo or answer access forbidden\n'})},
        'dino/resource.json':{'tail_utf8':json.dumps({'outcome':'child_failed','returncode':1,
            'elapsed_seconds':4.2,'wait4_peak_resident_bytes':123456,'error':'private patient name'})}})
    actual=diagnostics.safe_log_summary(value)
    assert actual['reason_codes']==['dino_access_guard','dino_worker_failure']
    assert actual['worker_errors']==[{'log':'dino/logs.json','error_type':'RuntimeError'}]
    assert actual['resources']==dict(outcome='child_failed',returncode=1,elapsed_seconds=4.2,
        wait4_peak_resident_bytes=123456,error={'category':'other','errno':None})
    assert 'private' not in json.dumps(actual)


def test_no_paths_filenames_labels_base64_or_custom_names_escape():
    secret='PatientName_photo.png /private/PatientName/photo.png data:image/png;base64,SECRETDATA'
    value=example(phase=secret,error_type=secret,message=secret,details={'image':secret},log_tails={
        'infer.log':{'tail_utf8':'FileNotFoundError: '+secret},
        secret:{'tail_utf8':'ValueError: '+secret}})
    actual=diagnostics.safe_log_summary(value)
    assert actual['phase']==actual['error_type']=='other'
    assert actual['reason_codes']==['unclassified']
    assert actual['worker_errors']==[{'log':'infer.log','error_type':'FileNotFoundError'}]
    assert actual['raw_text_logged'] is False
    assert all(word not in json.dumps(actual) for word in ('PatientName','SECRETDATA','base64','/private'))


def test_malformed_resource_and_nonfinite_numeric_are_not_logged():
    actual=diagnostics.safe_log_summary(example(details={'returncode':False,'elapsed_seconds':float('inf')},
        log_tails={'dino/resource.json':{'tail_utf8':'{"secret":"truncated'}}))
    assert actual['details']==actual['resources']=={}
    actual=diagnostics.safe_log_summary(example(log_tails={'dino/resource.json':{'tail_utf8':
        '{"outcome":"/private/name","returncode":true,"elapsed_seconds":NaN}'}}))
    assert actual['resources']=={}


def test_preserve_emits_one_safe_line_and_keeps_original_local_diagnostic(tmp_path,capsys):
    logs=tmp_path/'worker';logs.mkdir()
    (logs/'infer.log').write_text('RuntimeError: No module named "/private/user_secret.png"\n')
    error=RuntimeError('failed /private/user_secret.png')
    with patch.object(diagnostics,'ROOT',tmp_path/'diagnostics'):
        identifier=diagnostics.preserve_failure(error,phase='local-worker:infer',folder=logs,
                                               details={'returncode':1,'elapsed_seconds':1.5})
        assert diagnostics.preserve_failure(error,phase='fusion-preview')==identifier
    lines=capsys.readouterr().err.splitlines()
    assert len(lines)==1 and lines[0].startswith('WECFU_RUNTIME_DIAGNOSTIC ')
    safe=json.loads(lines[0].split(' ',1)[1])
    assert safe['diagnostic_id']==identifier==error.diagnostic_id
    assert safe['reason_codes']==['missing_module']
    assert 'user_secret' not in lines[0]
    saved=json.loads((tmp_path/'diagnostics'/f'{identifier}.json').read_text())
    assert saved['message']==str(error)
    assert 'user_secret' in saved['log_tails']['infer.log']['tail_utf8']


def test_stderr_failure_does_not_replace_saved_inference_error(tmp_path):
    class Broken(StringIO):
        def write(self,*args):raise OSError('closed')
    error=ValueError('fixed runtime')
    with patch.object(diagnostics,'ROOT',tmp_path),patch.object(diagnostics.sys,'stderr',Broken()):
        identifier=diagnostics.preserve_failure(error,phase='fusion-preview')
    assert (tmp_path/f'{identifier}.json').is_file()
    assert error.diagnostic_id==identifier


def test_static_loading_guards_can_be_distinguished_without_argument_values():
    actual=diagnostics.safe_log_summary(example(log_tails={'dino/logs.json':{'tail_utf8':
        'ValueError: unknown initial global; stop: PrivateName\n'}}))
    assert 'unexpected_safe_global' in actual['reason_codes']
    assert 'PrivateName' not in json.dumps(actual)


def resource_summary(resource):
    return diagnostics.safe_log_summary(example(log_tails={
        'dino/resource.json':{'tail_utf8':json.dumps(resource)}}))['resources']


def test_exit_confirmation_failure_remains_distinct_from_final_normal_exit():
    resource={'outcome':'monitor_unavailable','returncode':0,'work_authorized':True,
        'error':"LinuxRSSUnavailable(3, 'own Linux child has no resident sample; confirm exit')",
        'resident_samples':9801,'instantaneous_RSS_hard_limit':False,
        'sampling_overshoot_possible':True,'descendant_or_GPU_resources_monitored':False,
        'exit_race_checks':[{'errno':3,'wait4_polls':11,'confirmed_exit':False,
                             'elapsed_seconds':.0501}]}
    actual=resource_summary(resource)
    assert actual['outcome']=='monitor_unavailable' and actual['returncode']==0
    assert actual['error']=={'category':'LinuxRSSUnavailable','errno':3}
    assert actual['exit_race_checks']==resource['exit_race_checks']
    assert actual['exit_race_checks_count']==1
    for key in ('work_authorized','resident_samples','instantaneous_RSS_hard_limit',
                'sampling_overshoot_possible','descendant_or_GPU_resources_monitored'):
        assert actual[key]==resource[key]


@pytest.mark.parametrize('error,category,number',[
    ("ProcessLookupError(3, '/private/person.png')",'ProcessLookupError',3),
    ("PermissionError(13, '/private/person.png')",'PermissionError',13),
    ("OSError(5, '/private/person.png')",'OSError',5),
    ("ValueError('invalid Linux resident sample /private/person.png')",'ValueError',None),
    ("IndexError('/private/person.png')",'IndexError',None),
    ("PrivatePatientError('/private/person.png')",'other',None),
    ("PermissionError(True, '/private/person.png')",'PermissionError',None),
    ("OSError(99999, '/private/person.png')",'OSError',None),
])
def test_resource_error_classification_never_forwards_arguments(error,category,number):
    actual=resource_summary({'error':error})
    assert actual=={'error':{'category':category,'errno':number}}
    assert all(secret not in json.dumps(actual) for secret in ('private','person.png','PrivatePatient'))


def test_exit_race_records_enforce_field_types_and_bound_output():
    rows=[{'errno':True,'wait4_polls':False,'confirmed_exit':1,'elapsed_seconds':float('nan'),
           'filename':'/private/person.png'},
          {'errno':13,'wait4_polls':0,'confirmed_exit':False,'elapsed_seconds':0,
           'error':'PrivatePatient'},
          {'errno':-1,'wait4_polls':1025,'confirmed_exit':'False','elapsed_seconds':-1}]
    actual=resource_summary({'exit_race_checks':rows})
    assert actual=={'exit_race_checks':[{'errno':13,'wait4_polls':0,
        'confirmed_exit':False,'elapsed_seconds':0}],'exit_race_checks_count':3}
    actual=resource_summary({'exit_race_checks':[rows[1]]*20})
    assert len(actual['exit_race_checks'])==16 and actual['exit_race_checks_count']==20
    assert 'PrivatePatient' not in json.dumps(actual)
    assert resource_summary({'exit_race_checks':'PrivatePatient','error':{'secret':'person'},
        'work_authorized':1,'resident_samples':True,'sampling_overshoot_possible':'true'})=={}


def test_preserve_failure_logs_safe_resource_fields_but_retains_local_error(tmp_path,capsys):
    logs=tmp_path/'worker';(logs/'dino').mkdir(parents=True)
    raw={'outcome':'monitor_unavailable','returncode':0,'work_authorized':True,
         'error':"PermissionError(13, '/private/PrivatePatient.png')",'exit_race_checks':[]}
    (logs/'dino/resource.json').write_text(json.dumps(raw))
    with patch.object(diagnostics,'ROOT',tmp_path/'diagnostics'):
        identifier=diagnostics.preserve_failure(ValueError('single-image resource/runtime failure'),
            phase='fusion-dino',folder=logs)
    emitted=capsys.readouterr().err.splitlines()
    assert len(emitted)==1 and 'PrivatePatient' not in emitted[0]
    safe=json.loads(emitted[0].split(' ',1)[1])
    assert safe['resources']['error']=={'category':'PermissionError','errno':13}
    assert safe['resources']['exit_race_checks']==[]
    saved=json.loads((tmp_path/'diagnostics'/f'{identifier}.json').read_text())
    assert json.loads(saved['log_tails']['dino/resource.json']['tail_utf8'])==raw
