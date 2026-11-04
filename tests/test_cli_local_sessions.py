"""Local GUI lifetime tests; no server sockets, photographs or models."""

import argparse
import sys
from types import SimpleNamespace

import pytest
import uvicorn

from wecfu import cli
from wecfu.server import app as server


def stub_server_run(monkeypatch, callback):
    def run(instance, sockets=None):
        assert sockets is None
        config = instance.config
        return callback(config.app, host=config.host, port=config.port, log_level=config.log_level)

    monkeypatch.setattr(uvicorn.Server, "run", run)


@pytest.fixture
def local_session(monkeypatch, tmp_path):
    temp_parent = tmp_path / "system-temp"
    temp_parent.mkdir()
    monkeypatch.setattr(cli.tempfile, "tempdir", str(temp_parent))
    roots = []

    def build_app(*, get_root, web_mode):
        assert web_mode is False
        root = get_root()
        assert root.is_dir()
        assert (root / "inputs").is_dir()
        assert (root / "runs").is_dir()
        roots.append(root)
        return SimpleNamespace(get_root=get_root)

    monkeypatch.setattr(server, "build_app", build_app)
    return SimpleNamespace(
        roots=roots,
        temp_parent=temp_parent,
        args=argparse.Namespace(root=None, port=9876, open=False, model_setup=False),
    )


def test_default_starts_isolated_sessions_without_touching_old_workspaces(
    local_session, monkeypatch, tmp_path
):
    legacy = tmp_path / "data"
    legacy.mkdir()
    (legacy / "keep.json").write_text("old workspace")
    orphan = local_session.temp_parent / "wecfu-local-unowned-orphan"
    orphan.mkdir()
    (orphan / "keep.json").write_text("not owned by this process")
    monkeypatch.chdir(tmp_path)

    def serve(app, **kwargs):
        root = app.get_root()
        assert root != legacy
        assert root.parent == local_session.temp_parent
        assert kwargs == {"host": "127.0.0.1", "port": 9876, "log_level": "info"}
        assert list((root / "inputs").iterdir()) == []
        assert list((root / "runs").iterdir()) == []
        (root / "runs" / "current.json").write_text("this session")
        # Repeated page requests keep the same workspace until the server exits.
        assert app.get_root() == root
        assert (app.get_root() / "runs" / "current.json").read_text() == "this session"

    stub_server_run(monkeypatch, serve)
    for _ in range(2):
        assert cli._cmd_serve(local_session.args) == 0
        assert not local_session.roots[-1].exists()
    assert local_session.roots[0] != local_session.roots[1]
    assert (legacy / "keep.json").read_text() == "old workspace"
    assert (orphan / "keep.json").read_text() == "not owned by this process"


@pytest.mark.parametrize("failure", [RuntimeError, KeyboardInterrupt, SystemExit])
def test_temporary_session_cleans_up_when_server_raises(
    local_session, monkeypatch, failure
):
    def fail(app, **kwargs):
        (app.get_root() / "runs" / "partial.json").write_text("partial result")
        raise failure("synthetic server exit")

    stub_server_run(monkeypatch, fail)
    with pytest.raises(failure, match="synthetic server exit"):
        cli._cmd_serve(local_session.args)
    assert len(local_session.roots) == 1
    assert not local_session.roots[0].exists()


def test_temporary_session_cleans_up_after_app_creation_failure(local_session, monkeypatch):
    roots = []

    def fail(*, get_root, web_mode):
        roots.append(get_root())
        raise RuntimeError("synthetic initialization failure")

    monkeypatch.setattr(server, "build_app", fail)
    with pytest.raises(RuntimeError, match="initialization failure"):
        cli._cmd_serve(local_session.args)
    assert len(roots) == 1
    assert not roots[0].exists()


def test_cleanup_unlinks_imports_without_touching_original_files_or_directories(
    local_session, monkeypatch, tmp_path
):
    originals = tmp_path / "originals"
    originals.mkdir()
    original = originals / "synthetic.txt"
    original.write_bytes(b"read-only source bytes")
    original.chmod(0o444)

    def serve(app, **kwargs):
        inputs = app.get_root() / "inputs"
        (inputs / "source-link").symlink_to(original)
        (inputs / "directory-link").symlink_to(originals, target_is_directory=True)
        (inputs / "uploaded-copy.txt").write_bytes(b"workspace copy")

    stub_server_run(monkeypatch, serve)
    assert cli._cmd_serve(local_session.args) == 0
    assert not local_session.roots[0].exists()
    assert originals.is_dir()
    assert original.read_bytes() == b"read-only source bytes"
    assert original.stat().st_mode & 0o777 == 0o444


@pytest.mark.parametrize("server_fails", [False, True])
def test_explicit_root_keeps_existing_and_new_results(
    local_session, monkeypatch, tmp_path, server_fails
):
    root = tmp_path / "persistent"
    (root / "inputs").mkdir(parents=True)
    (root / "runs").mkdir()
    (root / "inputs" / "old.txt").write_text("existing import")
    (root / "runs" / "old.json").write_text("existing edits")
    local_session.args.root = str(root)

    def serve(app, **kwargs):
        assert app.get_root() == root
        (root / "runs" / "new.json").write_text("new edits")
        if server_fails:
            raise RuntimeError("synthetic server exit")

    stub_server_run(monkeypatch, serve)
    if server_fails:
        with pytest.raises(RuntimeError, match="server exit"):
            cli._cmd_serve(local_session.args)
    else:
        assert cli._cmd_serve(local_session.args) == 0
    assert (root / "inputs" / "old.txt").read_text() == "existing import"
    assert (root / "runs" / "old.json").read_text() == "existing edits"
    assert (root / "runs" / "new.json").read_text() == "new edits"
    assert list(local_session.temp_parent.iterdir()) == []


@pytest.mark.parametrize("extra_args, expected_root, model_setup", [
    ([], None, True),
    (["--root", "./saved"], "./saved", True),
    (["--no-model-setup"], None, False),
])
def test_serve_parser_only_persists_when_root_is_explicit(monkeypatch, extra_args, expected_root, model_setup):
    seen = []
    monkeypatch.setattr(sys, "argv", ["wecfu", "serve", "--no-open", *extra_args])
    monkeypatch.setattr(cli, "_cmd_serve", lambda args: seen.append(args) or 0)
    assert cli.main() == 0
    assert len(seen) == 1
    assert seen[0].root == expected_root
    assert seen[0].open is False
    assert seen[0].model_setup is model_setup


@pytest.mark.parametrize("setup_fails", [False, True])
def test_automatic_ultra_setup_precedes_app_creation_and_reports_failure(
    local_session, monkeypatch, capsys, setup_fails
):
    events = []
    original_build = server.build_app

    def ensure_ultra():
        events.append("setup")
        if setup_fails:
            raise RuntimeError("synthetic offline setup")
        return {"available": True}

    def build_app(**kwargs):
        events.append("build")
        return original_build(**kwargs)

    monkeypatch.setitem(sys.modules, "wecfu.runtime_bootstrap", SimpleNamespace(ensure_ultra=ensure_ultra))
    monkeypatch.setattr(server, "build_app", build_app)
    stub_server_run(monkeypatch, lambda app, **kwargs: events.append("serve"))
    local_session.args.model_setup = True
    assert cli._cmd_serve(local_session.args) == 0
    assert events == ["setup", "build", "serve"]
    assert not local_session.roots[0].exists()
    stderr = capsys.readouterr().err
    if setup_fails:
        assert "Ultra setup failed: synthetic offline setup; Lite remains available." in stderr
    else:
        assert stderr == ""


def test_explicit_offline_flag_never_runs_setup(local_session, monkeypatch):
    def forbidden():
        pytest.fail("offline launch must not attempt model setup")

    monkeypatch.setitem(sys.modules, "wecfu.runtime_bootstrap", SimpleNamespace(ensure_ultra=forbidden))
    stub_server_run(monkeypatch, lambda app, **kwargs: None)
    local_session.args.model_setup = False
    assert cli._cmd_serve(local_session.args) == 0
