"""Synthetic archive safety checks; no network, weights, models or photographs."""
import hashlib
import io
import tarfile

import pytest

from wecfu.setup_models import _install_sam_source

ROOT = 'sam2-fixed'
DATA = b'original official config\n'


def manifest():
    return {'commit':'fixed', 'files_sha256':{'sam2/alias.yaml':hashlib.sha256(DATA).hexdigest()},
            'files_bytes':{'sam2/alias.yaml':len(DATA)}}


def archive(entries):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w') as tar:
        for name, kind, payload in entries:
            entry = tarfile.TarInfo(name)
            entry.type = kind
            if kind == tarfile.REGTYPE:
                entry.size = len(payload)
                tar.addfile(entry, io.BytesIO(payload))
            else:
                entry.linkname = payload
                tar.addfile(entry)
    output.seek(0)
    return tarfile.open(fileobj=output, mode='r:')


def install(tmp_path, entries, spec=None):
    with archive(entries) as tar:
        _install_sam_source(tar, tmp_path/'source', spec or manifest())


@pytest.mark.parametrize('kind,target', [
    (tarfile.SYMTYPE, 'configs/original.yaml'),
    (tarfile.LNKTYPE, ROOT+'/sam2/configs/original.yaml'),
])
def test_official_style_alias_copies_verified_regular_bytes_not_link(tmp_path, kind, target):
    entries=[(ROOT+'/sam2/alias.yaml',kind,target),
             (ROOT+'/sam2/configs/original.yaml',tarfile.REGTYPE,DATA)]
    install(tmp_path,entries)
    dest=tmp_path/'source/sam2/alias.yaml'
    assert dest.read_bytes()==DATA and not dest.is_symlink()
    assert not (tmp_path/'source/sam2/configs').exists(), 'Only required output is installed'
    before=dest.stat().st_mtime_ns
    install(tmp_path,entries)
    assert dest.stat().st_mtime_ns==before


def test_regular_source_and_internal_alias_chain(tmp_path):
    entries=[(ROOT+'/sam2/alias.yaml',tarfile.SYMTYPE,'nested/next.yaml'),
             (ROOT+'/sam2/nested/next.yaml',tarfile.SYMTYPE,'../configs/original.yaml'),
             (ROOT+'/sam2/configs/original.yaml',tarfile.REGTYPE,DATA)]
    install(tmp_path,entries)
    assert (tmp_path/'source/sam2/alias.yaml').read_bytes()==DATA
    with archive([(ROOT+'/sam2/alias.yaml',tarfile.REGTYPE,DATA)]) as tar:
        _install_sam_source(tar,tmp_path/'regular',manifest())
    assert (tmp_path/'regular/sam2/alias.yaml').read_bytes()==DATA


@pytest.mark.parametrize('entries', [
    [(ROOT+'/sam2/alias.yaml',tarfile.SYMTYPE,'/etc/passwd')],
    [(ROOT+'/sam2/alias.yaml',tarfile.SYMTYPE,'../../outside')],
    [(ROOT+'/sam2/alias.yaml',tarfile.LNKTYPE,'other-root/file')],
    [(ROOT+'/sam2/alias.yaml',tarfile.SYMTYPE,'bad\\target')],
    [(ROOT+'/sam2/alias.yaml',tarfile.SYMTYPE,'missing')],
    [(ROOT+'/sam2/alias.yaml',tarfile.SYMTYPE,'alias.yaml')],
    [(ROOT+'/sam2/alias.yaml',tarfile.SYMTYPE,'second'),
     (ROOT+'/sam2/second',tarfile.SYMTYPE,'alias.yaml')],
    [(ROOT+'/sam2/alias.yaml',tarfile.SYMTYPE,'target'),
     (ROOT+'/sam2/target',tarfile.DIRTYPE,'')],
    [(ROOT+'/sam2/alias.yaml',tarfile.FIFOTYPE,'')],
    [(ROOT+'/sam2/alias.yaml',tarfile.REGTYPE,DATA)]*2,
    [(ROOT+'/sam2/alias.yaml',tarfile.SYMTYPE,'target'),
     (ROOT+'/sam2/target',tarfile.REGTYPE,DATA),
     (ROOT+'/sam2/target',tarfile.REGTYPE,DATA)],
    [('/'+ROOT+'/sam2/alias.yaml',tarfile.REGTYPE,DATA)],
    [(ROOT+'/../sam2/alias.yaml',tarfile.REGTYPE,DATA)],
])
def test_unsafe_ambiguous_or_nonregular_archive_rejected_before_writing(tmp_path, entries):
    with pytest.raises(RuntimeError):install(tmp_path,entries)
    assert not (tmp_path/'source').exists()


@pytest.mark.parametrize('data',[b'x',b'X'*len(DATA)])
def test_alias_target_must_match_both_pinned_size_and_digest(tmp_path,data):
    with pytest.raises(RuntimeError):install(tmp_path,[
        (ROOT+'/sam2/alias.yaml',tarfile.SYMTYPE,'target'),
        (ROOT+'/sam2/target',tarfile.REGTYPE,data)])
    assert not (tmp_path/'source/sam2/alias.yaml').exists()
    assert not list(tmp_path.rglob('.asset-*'))


def test_existing_different_destination_never_overwritten(tmp_path):
    destination=tmp_path/'source/sam2/alias.yaml'
    destination.parent.mkdir(parents=True); destination.write_bytes(b'leave this alone')
    with pytest.raises(RuntimeError):install(tmp_path,[(ROOT+'/sam2/alias.yaml',tarfile.REGTYPE,DATA)])
    assert destination.read_bytes()==b'leave this alone'
