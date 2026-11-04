"""Local SAM2 D0 provider. No labels, experiment runners or cached predictions.

Each request uses fresh temporary source bytes and separate CV / SAM interpreters.
The app never imports Torch. Its controller enforces one whole-request deadline
and sampled child RSS; the SAM child additionally checks its MPS allocation.
"""
from __future__ import annotations

from dataclasses import asdict
import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
from . import runtime_diagnostics
from wecfu import runtime_paths
from wecfu.runtime_bootstrap import isolated_environment

ENGINE = "sam2_local_v1"
RECIPE_ID = "sam_cv_seed_area0.05_color160_edge095_v1"
MODEL_SHA256 = "7402e0d864fa82708a20fbd15bc84245c2f26dff0eb43a4b5b93452deb34be69"
SOURCE_COMMIT = "2b90b9f5ceec907a1c18123530e92e794ad901a4"
PLATE_INSET = .95
TIMEOUT_SECONDS = 120.0
RSS_LIMIT_BYTES = 4 * 1024**3
MAX_JSON_BYTES = 256 * 1024**2
REPO = Path(__file__).resolve().parents[2]
RUNTIME = runtime_paths.MODEL_HOME
SAM_PYTHON = runtime_paths.MODEL_PYTHON
CV_PYTHON = runtime_paths.CV_PYTHON
SOURCE = runtime_paths.SAM_SOURCE
CHECKPOINT = runtime_paths.SAM_CHECKPOINT
SAM_DEVICE = runtime_paths.SAM_DEVICE
WORKER = Path(__file__).with_name("sam_worker.py")
AUTHORIZATION = Path(__file__).with_name("sam2_product_use.json")
COMPONENT_PARAMS = dict(plate_inset=.95, min_area_frac=.0001, max_area_frac=.05,
                        min_circularity=.55, max_eccentricity=.88, min_solidity=.8,
                        peak_min_distance=15, peak_rel_threshold=.5,
                        min_value=200, max_saturation=160)
MODEL_SETTINGS = dict(points_per_side=None, points_per_batch=4, pred_iou_thresh=.8,
                      stability_score_thresh=.95, stability_score_offset=1.0,
                      mask_threshold=0.0, box_nms_thresh=.7, crop_n_layers=0,
                      min_mask_region_area=0, output_mode="uncompressed_rle",
                      use_m2m=False, multimask_output=True)


class RuntimeUnavailable(RuntimeError):
    pass


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024**2), b""):
            digest.update(block)
    return digest.hexdigest()


def fingerprint(path):
    s = Path(path).stat()
    return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)


def sampled_rss(pid):
    """Read resident bytes of this isolated single-process worker; fail closed."""
    if sys.platform == "linux":
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
        raise RuntimeUnavailable("Cannot sample local model memory")
    # Darwin's own-child task information avoids spawning ps in a sandbox.
    class TaskInfo(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in (
            "virtual_size", "resident_size", "total_user", "total_system", "threads_user", "threads_system")]
        _fields_ += [(name, ctypes.c_int32) for name in (
            "policy", "faults", "pageins", "cow_faults", "messages_sent", "messages_received",
            "syscalls_mach", "syscalls_unix", "csw", "threadnum", "numrunning", "priority")]
    if sys.platform != "darwin" or ctypes.sizeof(TaskInfo) != 96:
        raise RuntimeUnavailable("Unsupported local memory monitor")
    library = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    query = library.proc_pidinfo
    query.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
    query.restype = ctypes.c_int
    info = TaskInfo()
    ctypes.set_errno(0)
    size = query(pid, 4, 0, ctypes.byref(info), ctypes.sizeof(info))
    if size != ctypes.sizeof(info):
        number = ctypes.get_errno()
        if number == errno.ESRCH:
            raise ProcessLookupError(pid)
        raise RuntimeUnavailable("Local model memory monitor became unavailable")
    if info.resident_size <= 0:
        raise RuntimeUnavailable("Invalid local model memory sample")
    return int(info.resident_size)


def stop_process(process):
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=4)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeUnavailable("Local model process could not be stopped") from exc


def confirm_child_exit(process, deadline):
    """Bounded same-child poll; an alive/unreapable child never passes as success."""
    until = min(deadline, time.monotonic() + .05)
    for _ in range(11):
        if process.poll() is not None:
            return True
        remaining = until - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(.005, remaining))
    return process.poll() is not None


def run_stage(command, folder, deadline, env):
    """No unbounded pipes; preserve failure log tail before temporary cleanup."""
    if time.monotonic() >= deadline:
        raise RuntimeUnavailable("Local model preview exceeded 120 seconds")
    log = folder / (command[-1] + ".log")
    peak = 0
    started = time.monotonic()
    process = None
    try:
        with log.open("xb") as output:
            process = subprocess.Popen(command, cwd=REPO, env=env, stdout=output,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            try:
                while process.poll() is None:
                    if time.monotonic() >= deadline:
                        raise RuntimeUnavailable("Local model preview exceeded 120 seconds")
                    try:
                        peak = max(peak, sampled_rss(process.pid))
                    except (ProcessLookupError, FileNotFoundError, RuntimeUnavailable) as sample_error:
                        if not confirm_child_exit(process, deadline):
                            raise RuntimeUnavailable("Local model memory monitor became unavailable while child was still active") from sample_error
                        break
                    if peak > RSS_LIMIT_BYTES:
                        raise RuntimeUnavailable("Local model preview exceeded the 4 GiB memory budget")
                    if any(p.stat().st_size > MAX_JSON_BYTES for p in folder.iterdir() if p.is_file() and p.suffix in {".json", ".log"}):
                        raise RuntimeUnavailable("Local model preview output exceeded its storage budget")
                    time.sleep(.1)
                if process.returncode:
                    raise RuntimeUnavailable("Local model failed; no candidate was created")
                if time.monotonic() >= deadline:
                    raise RuntimeUnavailable("Local model preview exceeded 120 seconds")
            finally:
                stop_process(process)
    except Exception as exc:
        # Diagnostic persistence must not hide the primary inference error.
        try:
            runtime_diagnostics.preserve_failure(exc,phase="local-worker:"+command[-1],folder=folder,
                details={"returncode":getattr(process,"returncode",None),"elapsed_seconds":time.monotonic()-started,"sampled_peak_rss_bytes":peak,"recipe_unchanged":True})
        except Exception:
            pass
        raise
    return peak


class LocalSamProvider:
    def __init__(self, *, web_mode=False, enable_for_fusion=False):
        self.enabled = os.environ.get("WECFU_ENABLE_SAM2", "1") != "0"
        self._guard = threading.Lock()
        self._checked_checkpoint = None
        self._checked_runtime = None
        self.last_timings = None

    def require_available(self):
        if sys.platform not in ('darwin', 'linux'):
            raise RuntimeUnavailable("Local SAM2/Fusion models require macOS or Linux; the core application remains available")
        if not self.enabled:
            raise RuntimeUnavailable("Local SAM2 preview is not enabled")
        try:
            authority = json.loads(AUTHORIZATION.read_bytes())
            if (authority.get("approved_for_product_inference") is not True
                    or authority.get("model_sha256") != MODEL_SHA256
                    or authority.get("source_commit") != SOURCE_COMMIT
                    or authority.get("recipe_id") != RECIPE_ID
                    or authority.get("code_license") != "Apache-2.0"
                    or authority.get("weights_license") != "Apache-2.0"):
                raise RuntimeUnavailable("Local SAM2 authorization does not match this recipe")
            if not all(p.is_file() for p in (SAM_PYTHON, CV_PYTHON, CHECKPOINT, WORKER)):
                raise RuntimeUnavailable("Local SAM2 runtime or weights are missing; no download will be attempted")
            before = fingerprint(CHECKPOINT)
            with self._guard:
                if self._checked_checkpoint != before:
                    if sha(CHECKPOINT) != MODEL_SHA256 or fingerprint(CHECKPOINT) != before:
                        raise RuntimeUnavailable("Local SAM2 weights failed integrity verification")
                    self._checked_checkpoint = before
            if runtime_paths.verify_sam_source() != SOURCE_COMMIT:
                raise RuntimeUnavailable("SAM2 source differs from its pinned revision")
            runtime_key = (fingerprint(SAM_PYTHON), fingerprint(CV_PYTHON), SAM_DEVICE)
            if self._checked_runtime != runtime_key:
                from wecfu.runtime_bootstrap import _probe
                environment = {**isolated_environment(os.environ), "PYTHONDONTWRITEBYTECODE":"1",
                               "PYTHONNOUSERSITE":"1", "WECFU_SAM_DEVICE":SAM_DEVICE,
                               "HF_HUB_OFFLINE":"1", "TRANSFORMERS_OFFLINE":"1"}
                try:
                    _probe(SAM_PYTHON, RUNTIME, env=environment)
                    if CV_PYTHON != SAM_PYTHON:
                        _probe(CV_PYTHON, RUNTIME, env=environment)
                except RuntimeError as exc:
                    raise RuntimeUnavailable("Ultra runtime is not ready. Restart WeCFU to prepare it. " + str(exc)) from exc
                self._checked_runtime = runtime_key
            return before
        except RuntimeUnavailable:
            raise
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            raise RuntimeUnavailable("Local SAM2 runtime cannot be verified") from exc

    def capability(self):
        reason = None
        try:
            self.require_available()
        except RuntimeUnavailable as exc:
            reason = str(exc)
        return dict(enabled=self.enabled, available=reason is None, reason=reason,
                    engine=ENGINE, model_sha256=MODEL_SHA256, recipe_id=RECIPE_ID,
                    label="SAM2", plate_inset=PLATE_INSET, device=SAM_DEVICE, runtime_python=SAM_PYTHON.name)

    def predict(self, payload, plate, image_sha256, *, deadline=None):
        started = time.monotonic()
        deadline = min(started + TIMEOUT_SECONDS, deadline) if deadline is not None else started + TIMEOUT_SECONDS
        warm = os.environ.get("WECFU_SAM_WARM_WORKER", "1") == "1"
        timings = {"mode": "warm_worker" if warm else "cold", "status": "running"}
        pin = None if warm else self.require_available()
        if hashlib.sha256(payload).hexdigest() != image_sha256:
            raise RuntimeUnavailable("Local SAM2 source bytes changed")
        # The only copied input is the current displayed image; no filesystem
        # paths, human points, references, notes or person identity reach workers.
        with tempfile.TemporaryDirectory(prefix="wecfu-sam-preview-") as scratch:
            folder = Path(scratch)
            (folder / "source.image").write_bytes(payload)
            os.chmod(folder / "source.image", 0o400)
            request = dict(engine=ENGINE, recipe_id=RECIPE_ID, image_sha256=image_sha256,
                           plate=asdict(plate), model_sha256=MODEL_SHA256)
            (folder / "request.json").write_text(json.dumps(request, allow_nan=False))
            env = {**isolated_environment(os.environ), "PYTHONDONTWRITEBYTECODE": "1",
                   "PYTORCH_ENABLE_MPS_FALLBACK": "0", "HF_HUB_OFFLINE": "1",
                   "TRANSFORMERS_OFFLINE": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
                   "OPENBLAS_NUM_THREADS": "1", "VECLIB_MAXIMUM_THREADS": "1"}
            timings["before_seconds"] = time.monotonic() - started
            result = None

            def validate_result():
                nonlocal result
                result = json.loads((folder / "result.json").read_bytes())
                if (not isinstance(result, dict) or result.get("engine") != ENGINE or result.get("recipe_id") != RECIPE_ID
                        or result.get("image_sha256") != image_sha256 or result.get("model_sha256") != MODEL_SHA256
                        or result.get("plate") != asdict(plate) or result.get("status") != "ok"
                        or fingerprint(CHECKPOINT) != pin):
                    raise RuntimeUnavailable("Local SAM2 result provenance changed")
                if (not isinstance(result.get("detections"), list) or len(result["detections"]) > 20000
                        or type(result.get("raw_count")) is not int
                        or result["raw_count"] < len(result["detections"])):
                    raise RuntimeUnavailable("Local SAM2 produced invalid candidates")
                if time.monotonic() >= deadline:
                    raise RuntimeUnavailable("Local model preview exceeded 120 seconds")

            if warm:
                from . import sam_warm_pool

                def verify_pins():
                    nonlocal pin
                    pin = self.require_available()
                    # A resident interpreter must not survive a changed worker,
                    # interpreter, source manifest, authorization or settings.
                    files = (SAM_PYTHON, CV_PYTHON, WORKER, AUTHORIZATION,
                             Path(__file__), Path(sam_warm_pool.__file__),
                             runtime_paths.PACKAGE_ROOT / "model_assets.json",
                             Path(runtime_paths.__file__),
                             REPO / "wecfu/experiments/segmentation.py",
                             REPO / "wecfu/segment.py", REPO / "wecfu/plate.py")
                    return (pin, SOURCE_COMMIT, str(SOURCE.resolve()), SAM_DEVICE,
                            tuple((str(path.resolve()), fingerprint(path)) for path in files),
                            json.dumps([COMPONENT_PARAMS, MODEL_SETTINGS], sort_keys=True),
                            hashlib.sha256(json.dumps(env, sort_keys=True).encode()).hexdigest())

                try:
                    details = sam_warm_pool.POOL.run(folder=folder, deadline=deadline, env=env,
                        cv_python=CV_PYTHON, sam_python=SAM_PYTHON, worker=WORKER, repo=REPO,
                        verify_pins=verify_pins, sample_rss=sampled_rss, stop_process=stop_process,
                        rss_limit=RSS_LIMIT_BYTES, max_output=MAX_JSON_BYTES, validate_result=validate_result)
                    timings.update(details)
                except Exception as exc:
                    timings.update(status="failed", total_seconds=time.monotonic() - started)
                    self.last_timings = timings
                    try:
                        runtime_diagnostics.preserve_failure(exc, phase="local-worker:warm",
                            folder=folder, details={"elapsed_seconds": time.monotonic()-started,
                                                  "recipe_unchanged": True})
                    except Exception:
                        pass
                    if isinstance(exc, sam_warm_pool.WarmWorkerError):
                        raise RuntimeUnavailable(str(exc)) from exc
                    raise
            else:
                peaks = []
                timings.update(queue_seconds=0.0, worker_reused=False,
                                         worker_started={"prepare": True, "infer": True, "finish": True})
                for executable, stage in ((CV_PYTHON, "prepare"), (SAM_PYTHON, "infer"), (CV_PYTHON, "finish")):
                    stage_started = time.monotonic()
                    peaks.append(run_stage([str(executable), "-B", str(WORKER), str(folder), stage], folder, deadline, env))
                    timings[stage + "_seconds"] = time.monotonic() - stage_started
                timings["sampled_peak_combined_rss_bytes"] = max(peaks, default=0)
                validate_result()
            timings.update(status="ok", total_seconds=time.monotonic() - started)
            self.last_timings = timings
            return result["detections"], result["raw_count"]
