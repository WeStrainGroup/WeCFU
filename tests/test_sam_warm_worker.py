"""Synthetic worker protocol and cache isolation tests; no model/photo input."""
from contextlib import nullcontext
import json
import os
from pathlib import Path
import subprocess
import sys
from types import ModuleType, SimpleNamespace

import numpy as np
import pytest

from wecfu import runtime_paths
from wecfu.server import sam_worker as worker


def recipe(folder, **changes):
    folder.mkdir()
    (folder / "request.json").write_text(json.dumps(dict(
        engine=worker.ENGINE, recipe_id=worker.RECIPE_ID,
        model_sha256=worker.MODEL_SHA256) | changes))
    return folder


def command(folder, *, stage="prepare", token="test"):
    return dict(id=token, folder=str(folder), stage=stage)


def subprocess_worker(commands, *, mode="cv", handler="pass", extra="", idle=.2, maximum=32):
    script = f"""
import os, sys
from wecfu.server import sam_worker as w
def handler(folder, request, **kwargs):
    {handler}
w.prepare = w.finish = w.infer = handler
{extra}
sys.addaudithook(w.no_network)
w.serve({mode!r}, idle_seconds={idle!r}, max_requests={maximum!r})
"""
    payload = commands if isinstance(commands, bytes) else b"".join(
        json.dumps(item).encode() + b"\n" for item in commands)
    result = subprocess.run([sys.executable, "-B", "-c", script], input=payload,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            cwd=worker.REPO, timeout=10)
    assert result.returncode == 0, result.stderr.decode()
    return result, [json.loads(row) for row in result.stdout.splitlines()]


def test_two_buffered_requests_are_processed_in_order_and_native_stdout_is_separate(tmp_path):
    folder = recipe(tmp_path / "scratch")
    result, replies = subprocess_worker(
        [command(folder), command(folder, stage="finish", token="second")],
        handler="print('python noise'); os.write(1, b'native noise\\n')")
    assert replies == [dict(id="test", ok=True), dict(id="second", ok=True)]
    assert result.stderr.count(b"python noise") == 2
    assert result.stderr.count(b"native noise") == 2


@pytest.mark.skipif(os.name != 'nt', reason='Actual Win32 native standard-handle acceptance')
def test_native_windows_standard_handle_output_stays_out_of_protocol(tmp_path):
    folder = recipe(tmp_path / 'scratch')
    extra = '''
def native_noise():
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetStdHandle.argtypes = (wintypes.DWORD,)
    kernel.GetStdHandle.restype = wintypes.HANDLE
    kernel.WriteFile.argtypes = (wintypes.HANDLE, wintypes.LPCVOID, wintypes.DWORD,
                                ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID)
    kernel.WriteFile.restype = wintypes.BOOL
    count = wintypes.DWORD()
    data = b'Windows native noise\\n'
    assert kernel.WriteFile(kernel.GetStdHandle(-11), data, len(data), ctypes.byref(count), None)
'''
    result, replies = subprocess_worker([command(folder)], handler='native_noise()', extra=extra)
    assert replies == [dict(id='test', ok=True)]
    assert b'Windows native noise' in result.stderr


def test_request_bound_stops_without_consuming_later_command(tmp_path):
    folder = recipe(tmp_path / "scratch")
    _, replies = subprocess_worker([command(folder)] * 3, maximum=2)
    assert len(replies) == 2 and all(row["ok"] for row in replies)


def test_failure_replies_once_then_exits_and_bounds_error(tmp_path):
    folder = recipe(tmp_path / "scratch")
    result, replies = subprocess_worker([command(folder)] * 2,
        handler="raise RuntimeError(('\\x00☃\\\\\\\"' * 1000))")
    assert len(replies) == 1 and replies[0]["ok"] is False
    assert len(result.stdout) <= 2048
    assert len(replies[0]["error"]) == 768


@pytest.mark.parametrize("payload", [b"x" * 4096, b'{"id":"unterminated"}', b'not-json\n'])
def test_bad_line_fails_closed(payload):
    _, replies = subprocess_worker(payload)
    assert len(replies) == 1 and replies[0]["ok"] is False


@pytest.mark.parametrize("mode,stage", [("cv", "infer"), ("infer", "prepare"), ("infer", "finish")])
def test_stage_must_match_isolated_interpreter(tmp_path, mode, stage):
    folder = recipe(tmp_path / "scratch")
    _, replies = subprocess_worker([command(folder, stage=stage)], mode=mode)
    assert not replies[0]["ok"] and "stage" in replies[0]["error"]


@pytest.mark.parametrize("key,value", [("engine", "other"), ("recipe_id", "other"),
                                       ("model_sha256", "other")])
def test_each_request_checks_recipe_before_handler(tmp_path, key, value):
    folder = recipe(tmp_path / "scratch", **{key: value})
    _, replies = subprocess_worker([command(folder)], handler="raise AssertionError('must not execute')")
    assert replies[0] == dict(id="test", ok=False, error="Worker recipe mismatch")


@pytest.mark.parametrize("change", [dict(folder="relative"), dict(id="bad id"), dict(id=5), dict(extra=5)])
def test_protocol_rejects_invalid_fields(tmp_path, change):
    folder = recipe(tmp_path / "scratch")
    _, replies = subprocess_worker([command(folder) | change])
    assert not replies[0]["ok"]


@pytest.mark.parametrize("mode,module,stage", [("cv", "torch", "prepare"), ("infer", "cv2", "infer")])
def test_cross_interpreter_import_is_rejected(tmp_path, mode, module, stage):
    folder = recipe(tmp_path / "scratch")
    _, replies = subprocess_worker([command(folder, stage=stage)], mode=mode,
                                   extra=f"sys.modules[{module!r}] = object()")
    assert not replies[0]["ok"] and "must not import" in replies[0]["error"]


def test_network_calls_are_denied(tmp_path):
    folder = recipe(tmp_path / "scratch")
    _, replies = subprocess_worker([command(folder)],
        handler="sys.audit('socket.connect', None, ('127.0.0.1', 1))")
    assert replies[0] == dict(id="test", ok=False, error="SAM2 preview is local-only")


def test_reader_eof_and_idle_are_bounded():
    read_fd, write_fd = os.pipe()
    try:
        assert worker.ProtocolReader(read_fd).read(.01) is None
        os.close(write_fd)
        write_fd = None
        assert worker.ProtocolReader(read_fd).read(1) is None
    finally:
        os.close(read_fd)
        if write_fd is not None:
            os.close(write_fd)


def synthetic_inference(monkeypatch, *, fail=False):
    """Substitute the model ABI, retaining actual worker caching/control code."""
    builds, generators, saves, resets, rng_restores = [], [], [], [], []
    monkeypatch.delitem(sys.modules, "cv2", raising=False)
    monkeypatch.setattr(runtime_paths, "check_versions", lambda: None)
    monkeypatch.setattr(runtime_paths, "verify_sam_source", lambda: None)
    monkeypatch.setattr(worker, "SAM_DEVICE", "cpu")
    monkeypatch.setattr(worker, "self_peak_rss", lambda: 0)
    monkeypatch.setattr(worker, "source", lambda folder, _: folder)
    monkeypatch.setattr(worker, "checked_rgb", lambda _: np.zeros((2, 3, 3), np.uint8))
    monkeypatch.setattr(worker, "load", lambda folder, _: dict(width=3, height=2,
        seeds=[dict(x=int(folder.name), y=1)]))
    monkeypatch.setattr(worker, "save", lambda folder, name, value: saves.append((folder, name, value)))
    state = SimpleNamespace(clone=lambda: "post-build-rng")
    torch = ModuleType("torch")
    torch.float32 = object()
    torch.set_num_threads = torch.manual_seed = lambda _: None
    torch.get_rng_state = lambda: state
    torch.set_rng_state = rng_restores.append
    torch.inference_mode = nullcontext
    monkeypatch.setitem(sys.modules, "torch", torch)

    class Model:
        def eval(self):
            return self
        def parameters(self):
            yield SimpleNamespace(dtype=torch.float32)

    def build(*args, **kwargs):
        builds.append((args, kwargs))
        return Model()

    class Generator:
        def __init__(self, model, **kwargs):
            self.model, self.kwargs, self.image = model, kwargs, None
            self.predictor = SimpleNamespace(reset_predictor=lambda: resets.append(self))
            generators.append(self)
        def generate(self, image):
            self.image = image
            if fail:
                raise RuntimeError("synthetic generation failure")
            return [dict(synthetic=True)]

    package = ModuleType("sam2")
    package.__file__ = str(worker.SOURCE / "sam2" / "__init__.py")
    for name, attrs in (("build_sam", dict(build_sam2=build)),
                        ("automatic_mask_generator", dict(SAM2AutomaticMaskGenerator=Generator)),
                        ("sam2_image_predictor", {})):
        module = ModuleType("sam2." + name)
        module.__file__ = str(worker.SOURCE / "sam2" / (name + ".py"))
        module.__dict__.update(attrs)
        setattr(package, name, module)
        monkeypatch.setitem(sys.modules, "sam2." + name, module)
    monkeypatch.setitem(sys.modules, "sam2", package)
    return builds, generators, saves, resets, rng_restores


def test_warm_weights_reused_but_images_predictors_grids_and_results_are_fresh(monkeypatch):
    builds, generators, saves, resets, rng_restores = synthetic_inference(monkeypatch)
    cache = {}
    worker.infer(Path("1"), {}, model_cache=cache)
    worker.infer(Path("2"), {}, model_cache=cache)
    assert len(builds) == 1 and len(generators) == len(saves) == len(resets) == 2
    assert set(cache) == {"model", "cpu_rng"}
    assert generators[0].model is generators[1].model
    assert generators[0].predictor is not generators[1].predictor
    assert generators[0].image is not generators[1].image
    grids = [g.kwargs["point_grids"][0] for g in generators]
    assert grids[0] is not grids[1] and not np.array_equal(*grids)
    assert rng_restores == ["post-build-rng"]
    assert all({k: v for k, v in g.kwargs.items() if k != "point_grids"}
               == worker.MODEL_SETTINGS for g in generators)
    assert builds[0][1]["apply_postprocessing"] is False


def test_cold_calls_build_fresh_models_without_warm_rng_or_cleanup(monkeypatch):
    builds, generators, _, resets, rng_restores = synthetic_inference(monkeypatch)
    worker.infer(Path("1"), {})
    worker.infer(Path("2"), {})
    assert len(builds) == 2 and generators[0].model is not generators[1].model
    assert resets == rng_restores == []


def test_failed_generation_releases_image_predictor_and_writes_no_result(monkeypatch):
    _, generators, saves, resets, _ = synthetic_inference(monkeypatch, fail=True)
    with pytest.raises(RuntimeError, match="synthetic generation"):
        worker.infer(Path("1"), {}, model_cache={})
    assert resets == generators and saves == []
