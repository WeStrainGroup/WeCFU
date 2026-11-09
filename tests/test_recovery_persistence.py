"""Recovery durability/platform regressions; synthetic API state, no model run."""
import errno
import json
import os
from pathlib import Path
import stat

import pytest
from fastapi.testclient import TestClient

import wecfu.server.app as server
from test_public_fusion_contract import BASE, app, initialized, sha, upload
from test_practical_recognition_policy import install_sam, sam_request, apply_request


def recovery_folder(root):
    return root / 'runs/demo/model_preview_recovery/plate.png'


def test_native_directory_sync_capability_is_explicit():
    assert server._DIRECTORY_FSYNC_SUPPORTED is (os.name != 'nt')


def test_windows_adoption_keeps_file_sync_readable_recovery_and_retry(app, monkeypatch):
    application, root = app
    calls = install_sam(application, monkeypatch)
    monkeypatch.setattr(server, '_DIRECTORY_FSYNC_SUPPORTED', False)
    original_open, original_fsync = os.open, os.fsync
    file_syncs = []

    def no_directory_open(path, flags, *args, **kwargs):
        if Path(path) == recovery_folder(root):
            pytest.fail('Windows must not open a directory for CRT fsync')
        return original_open(path, flags, *args, **kwargs)

    def synced_file(fd):
        assert stat.S_ISREG(os.fstat(fd).st_mode)
        file_syncs.append(fd)
        return original_fsync(fd)

    with TestClient(application) as client:
        raw = upload(client); before = initialized(client)
        candidate = client.post(BASE + '/model-preview', json=sam_request(before, raw)).json()
        monkeypatch.setattr(server.os, 'open', no_directory_open)
        monkeypatch.setattr(server.os, 'fsync', synced_file)
        body = apply_request(candidate, before, raw)
        response = client.post(BASE + '/model-preview/apply', json=body)
        assert response.status_code == 200, response.text
        adopted = response.json()
        assert adopted['detections'] == candidate['detections'] and adopted['counted'] is True
        assert len(file_syncs) == 1 and len(calls) == 1
        assert client.post(BASE + '/model-preview/apply', json=body).json() == adopted
        assert len(file_syncs) == 1  # Existing receipt, no rewrite or second recovery.
        paths = list(recovery_folder(root).glob('*.json'))
        assert len(paths) == 1
        recovery = json.loads(paths[0].read_text())
        assert recovery['state'] == before
        assert recovery['state_sha256'] == server.model_preview.state_signature(before)
        assert recovery['source_sha256'] == sha(raw)
        listed = client.get(BASE + '/model-preview/recovery').json()['snapshots']
        assert [r['recovery_id'] for r in listed] == [recovery['recovery_id']]
        restored = client.post(BASE + '/model-preview/restore', json={
            'recovery_id': recovery['recovery_id'], 'expected_revision': adopted['revision'],
            'expected_image_sha256': sha(raw), 'replace_all': True})
        assert restored.status_code == 200, restored.text
        assert {k:v for k,v in restored.json().items() if k != 'revision'} == {
            k:v for k,v in before.items() if k != 'revision'}
        assert len(file_syncs) == 2 and len(calls) == 1
        assert (root / 'inputs/demo/plate.png').read_bytes() == raw
        assert not server._reference_path(root, 'demo', 'plate.png').exists()


@pytest.mark.parametrize('failure', ['file_sync', 'directory_open', 'directory_sync', 'state_replace'])
def test_real_io_failures_never_adopt_or_replace_original_state(app, monkeypatch, failure):
    if failure == 'directory_sync' and os.name == 'nt':
        pytest.skip('POSIX directory-fd fsync failure; Windows deliberately cannot open that fd')
    application, root = app
    calls = install_sam(application, monkeypatch)
    # File fsync and state replace also remain mandatory on Windows. The two
    # POSIX directory failures are deliberately exercised on the POSIX branch.
    monkeypatch.setattr(server, '_DIRECTORY_FSYNC_SUPPORTED', failure.startswith('directory'))
    original_open, original_fsync, original_replace = os.open, os.fsync, os.replace
    directory_fds = []
    blocked = []

    def opened(path, flags, *args, **kwargs):
        if Path(path) == recovery_folder(root):
            if failure == 'directory_open':
                blocked.append(failure)
                raise PermissionError(errno.EACCES, 'synthetic directory access failure')
            fd = original_open(path, flags, *args, **kwargs)
            directory_fds.append(fd)
            return fd
        return original_open(path, flags, *args, **kwargs)

    def synced(fd):
        is_directory = stat.S_ISDIR(os.fstat(fd).st_mode)
        if failure == ('directory_sync' if is_directory else 'file_sync'):
            blocked.append(failure)
            raise OSError(errno.EIO, 'synthetic sync failure')
        return original_fsync(fd)

    def replaced(source, destination):
        if failure == 'state_replace' and Path(destination) == server._det_path(root, 'demo', 'plate.png'):
            blocked.append(failure)
            raise OSError(errno.EIO, 'synthetic atomic replace failure')
        return original_replace(source, destination)

    with TestClient(application, raise_server_exceptions=False) as client:
        raw = upload(client); state = initialized(client)
        candidate = client.post(BASE + '/model-preview', json=sam_request(state, raw)).json()
        target = server._det_path(root, 'demo', 'plate.png')
        before = target.read_bytes()
        reference = server._reference_path(root, 'demo', 'plate.png')
        reference.parent.mkdir(parents=True, exist_ok=True)
        reference.write_bytes(b'opaque synthetic reference sentinel')
        monkeypatch.setattr(server.os, 'open', opened)
        monkeypatch.setattr(server.os, 'fsync', synced)
        monkeypatch.setattr(server.os, 'replace', replaced)
        response = client.post(BASE + '/model-preview/apply', json=apply_request(candidate, state, raw))
        assert response.status_code == 500, response.text
        assert blocked == [failure]
        assert target.read_bytes() == before
        assert client.get(BASE + '/detections').json() == state
        assert (root / 'inputs/demo/plate.png').read_bytes() == raw
        assert reference.read_bytes() == b'opaque synthetic reference sentinel'
        assert len(calls) == 1
        assert not list(target.parent.glob('.' + target.name + '.*'))
        for fd in directory_fds:
            with pytest.raises(OSError) as closed:
                os.fstat(fd)
            assert closed.value.errno == errno.EBADF
