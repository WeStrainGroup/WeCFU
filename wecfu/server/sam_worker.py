"""One-image product worker. No reference/evaluation files or historic caches.

CV and Torch run in distinct interpreters to preserve the original D0 numeric
routines. This file copies only the audited seed and postprocessing operations;
it never imports an experiment runner with training/evaluation entry points.
"""
from __future__ import annotations
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import resource
import select
import sys
import time

REPO = Path(__file__).resolve().parents[2]
if __name__ == '__main__':
    # The app may be installed beside incompatible Conda dependencies. Bind
    # only WeCFU, leaving every numeric import in this worker's own runtime.
    import importlib.util
    package = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location('wecfu', package / '__init__.py',
                                                submodule_search_locations=[str(package)])
    module = importlib.util.module_from_spec(spec)
    sys.modules['wecfu'] = module
    spec.loader.exec_module(module)
from wecfu.server.sam_runtime import (CHECKPOINT, COMPONENT_PARAMS, ENGINE, MODEL_SETTINGS,
                                     MODEL_SHA256, PLATE_INSET, RECIPE_ID, RSS_LIMIT_BYTES,
                                     SOURCE, MAX_JSON_BYTES, SAM_DEVICE)


def no_network(event, args):
    if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto"}:
        raise RuntimeError("SAM2 preview is local-only")



def load(folder, name):
    path = folder / name
    if path.stat().st_size > MAX_JSON_BYTES:
        raise RuntimeError("Worker input exceeds storage budget")
    return json.loads(path.read_bytes())


def save(folder, name, value):
    raw = json.dumps(value, allow_nan=False, separators=(",", ":")).encode()
    if len(raw) > MAX_JSON_BYTES:
        raise RuntimeError("Worker output exceeds storage budget")
    with (folder / name).open("xb") as stream:
        stream.write(raw)


def source(folder, request):
    raw = (folder / "source.image").read_bytes()
    if hashlib.sha256(raw).hexdigest() != request["image_sha256"]:
        raise RuntimeError("Worker source integrity mismatch")
    return raw


def checked_rgb(raw):
    from PIL import Image
    with Image.open(io.BytesIO(raw)) as picture:
        if picture.getexif().get(274) not in (None, 1):
            raise RuntimeError("EXIF orientation must be absent or 1; no automatic image rotation")
        if picture.width * picture.height > 50_000_000:
            raise RuntimeError("Source image exceeds the local memory budget")
        return picture.convert("RGB")


def cv_seeds(im, plate, params):
    # Numeric body of round7 predict.cv_seeds, with exactly the same dependencies.
    import numpy as np
    from scipy import ndimage as ndi
    from wecfu.experiments.segmentation import _candidate_mask, _component_watershed_split_with_distance
    roi = plate.mask(im.shape[:2], shrink=params.plate_inset)
    bw = _candidate_mask(im, roi, params, 5, 9)
    labels, _, distance = _component_watershed_split_with_distance(bw, params)
    if distance is None:
        return []
    minimum = params.min_area_frac * math.pi * (plate.r * params.plate_inset)**2
    seeds = []
    for label, bounds in enumerate(ndi.find_objects(labels), 1):
        if bounds is None:
            continue
        member = labels[bounds] == label
        if int(member.sum()) < minimum:
            continue
        local = np.where(member, distance[bounds], -1)
        y, x = np.unravel_index(local.argmax(), local.shape)
        seeds.append(dict(x=int(x + bounds[1].start), y=int(y + bounds[0].start)))
    return seeds


def prepare(folder, request):
    import cv2
    import numpy as np
    from wecfu.plate import PlateCircle
    from wecfu.segment import SegmentParams
    cv2.setNumThreads(0)
    cv2.ocl.setUseOpenCL(False)
    raw = source(folder, request)
    rgb = checked_rgb(raw)
    im = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if im is None:
        raise RuntimeError("Source decode failed")
    height, width = im.shape[:2]
    if rgb.size != (width, height):
        raise RuntimeError("PIL/OpenCV image orientation or size differs")
    del rgb
    seeds = cv_seeds(im, PlateCircle(**request["plate"]), SegmentParams(**COMPONENT_PARAMS))
    save(folder, "prepared.json", dict(width=width, height=height, seeds=seeds))


def infer(folder, request, *, model_cache=None):
    from wecfu.runtime_paths import check_versions, verify_sam_source
    check_versions()
    verify_sam_source()
    import numpy as np
    prepared = load(folder, "prepared.json")
    image = np.array(checked_rgb(source(folder, request)), copy=True)
    if image.shape[:2] != (prepared["height"], prepared["width"]):
        raise RuntimeError("PIL/OpenCV image orientation or size differs")
    # D0 explicitly returns a successful empty candidate on zero CV seeds,
    # never a timeout/model-error disguised as zero.
    if not prepared["seeds"]:
        save(folder, "annotations.json", [])
        return
    sys.path.insert(0, str(SOURCE))
    import torch
    import sam2
    from sam2 import build_sam, automatic_mask_generator, sam2_image_predictor
    expected = {sam2: "__init__.py", build_sam: "build_sam.py",
                automatic_mask_generator: "automatic_mask_generator.py",
                sam2_image_predictor: "sam2_image_predictor.py"}
    if any(Path(mod.__file__).resolve() != (SOURCE / "sam2" / rel).resolve() for mod, rel in expected.items()):
        raise RuntimeError("SAM source module mismatch")
    if "cv2" in sys.modules:
        raise RuntimeError("The isolated model process must not import OpenCV")
    if SAM_DEVICE == "mps" and not torch.backends.mps.is_available():
        raise RuntimeError("Requested MPS device is unavailable; explicitly choose CPU instead")
    torch.set_num_threads(1)
    torch.manual_seed(0)
    if SAM_DEVICE == "mps": torch.mps.set_per_process_memory_fraction(.32)

    def memory_check():
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == "darwin" else 1024)
        if rss > RSS_LIMIT_BYTES or (SAM_DEVICE == "mps" and torch.mps.driver_allocated_memory() > RSS_LIMIT_BYTES):
            raise RuntimeError("SAM2 worker exceeds 4 GiB memory budget")

    class BoundedGenerator(automatic_mask_generator.SAM2AutomaticMaskGenerator):
        def _process_batch(self, *args, **kwargs):
            memory_check()
            result = super()._process_batch(*args, **kwargs)
            if SAM_DEVICE == "mps": torch.mps.synchronize()
            memory_check()
            return result

    # Only the optional persistent inference interpreter owns this cache. It
    # contains model weights and RNG state, never images, grids or predictions.
    if model_cache is not None and model_cache:
        model = model_cache["model"]
        torch.set_rng_state(model_cache["cpu_rng"])
        if SAM_DEVICE == "mps":
            torch.mps.set_rng_state(model_cache["device_rng"])
    else:
        model = build_sam.build_sam2("configs/sam2.1/sam2.1_hiera_t.yaml", str(CHECKPOINT),
                                     device=SAM_DEVICE, apply_postprocessing=False)
        model.eval()
        if model_cache is not None:
            model_cache.update(model=model, cpu_rng=torch.get_rng_state().clone())
            if SAM_DEVICE == "mps":
                model_cache["device_rng"] = torch.mps.get_rng_state().clone()
    if next(model.parameters()).dtype != torch.float32:
        raise RuntimeError("SAM2 model must remain float32")
    points = np.array([[s["x"] / prepared["width"], s["y"] / prepared["height"]]
                       for s in prepared["seeds"]], dtype=np.float32).reshape(-1, 2)
    generator = BoundedGenerator(model, **MODEL_SETTINGS, point_grids=[points])
    try:
        memory_check()
        with torch.inference_mode():
            annotations = generator.generate(image)
        if SAM_DEVICE == "mps": torch.mps.synchronize()
        memory_check()
        save(folder, "annotations.json", annotations)
    finally:
        # A new generator/predictor is constructed for every image. Explicitly
        # release its embeddings even if generation or serialization failed.
        if model_cache is not None:
            generator.predictor.reset_predictor()


def postprocess(annotations, plate, height, width):
    import numpy as np
    from wecfu.segment import _region_stats
    radius = plate["r"] * PLATE_INSET
    area = math.pi * radius**2
    accepted = []
    for ann in annotations:
        rle = ann["segmentation"]
        if rle["size"] != [height, width] or not isinstance(rle["counts"], list):
            raise RuntimeError("Invalid SAM mask dimensions")
        counts = rle["counts"]
        if any(type(n) is not int or n < 0 for n in counts) or sum(counts) != height * width:
            raise RuntimeError("Invalid SAM mask RLE")
        flat = np.zeros(height * width, np.uint8)
        at = 0
        for index, count in enumerate(counts):
            if index % 2:
                flat[at:at + count] = 1
            at += count
        mask = flat.reshape(width, height).T
        if int(mask.sum()) != ann["area"]:
            raise RuntimeError("SAM mask area mismatch")
        stats = _region_stats(mask)
        if not stats:
            continue
        keep = (.0001 * area <= ann["area"] <= .05 * area
                and math.hypot(stats["cx"] - plate["cx"], stats["cy"] - plate["cy"]) <= radius)
        if keep:
            # Circle is the original largest-contour enclosing circle. No shape
            # rejection or new NMS; quality score is not a class probability.
            accepted.append(dict(id=len(accepted) + 1, cx=stats["cx"], cy=stats["cy"], r=stats["r"],
                                 score=min(1., max(0., float(ann["predicted_iou"]))), accepted=True, source="cv"))
    return accepted


def finish(folder, request):
    import cv2
    cv2.setNumThreads(0)
    cv2.ocl.setUseOpenCL(False)
    prepared = load(folder, "prepared.json")
    annotations = load(folder, "annotations.json")
    detections = postprocess(annotations, request["plate"], prepared["height"], prepared["width"])
    source(folder, request)
    save(folder, "result.json", dict(**request, status="ok", raw_count=len(annotations), detections=detections))


def validated_request(folder):
    request = load(folder, "request.json")
    if (request.get("engine") != ENGINE or request.get("recipe_id") != RECIPE_ID
            or request.get("model_sha256") != MODEL_SHA256):
        raise RuntimeError("Worker recipe mismatch")
    return request


PROTOCOL_MAX_BYTES = 4096
# The parent reaps the whole idle pair after 90 seconds. Allow one other
# interpreter's full 120-second request before this child's own idle backstop.
PROTOCOL_IDLE_SECONDS = 210.0
PROTOCOL_MAX_REQUESTS = 32


class ProtocolReader:
    """Bounded binary reads; buffered lines never wait for another pipe event."""

    def __init__(self, descriptor):
        self.descriptor = descriptor
        self.pending = b""

    def read(self, idle_seconds):
        deadline = time.monotonic() + idle_seconds
        while True:
            end = self.pending.find(b"\n")
            if end >= 0:
                line, self.pending = self.pending[:end], self.pending[end + 1:]
                if len(line) + 1 > PROTOCOL_MAX_BYTES:
                    raise RuntimeError("Worker command exceeds protocol budget")
                return line
            if len(self.pending) >= PROTOCOL_MAX_BYTES:
                raise RuntimeError("Worker command exceeds protocol budget")
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([self.descriptor], [], [], remaining)[0]:
                return None
            chunk = os.read(self.descriptor, PROTOCOL_MAX_BYTES + 1 - len(self.pending))
            if not chunk:
                if self.pending:
                    raise RuntimeError("Incomplete worker command")
                return None
            self.pending += chunk


def protocol_command(raw, mode):
    command = json.loads(raw)
    if not isinstance(command, dict) or set(command) != {"id", "folder", "stage"}:
        raise RuntimeError("Invalid worker command fields")
    token = command["id"]
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", token):
        raise RuntimeError("Invalid worker command id")
    if command["stage"] not in ({"infer"} if mode == "infer" else {"prepare", "finish"}):
        raise RuntimeError("Worker stage does not match interpreter mode")
    if not isinstance(command["folder"], str) or not Path(command["folder"]).is_absolute():
        raise RuntimeError("Worker scratch path must be absolute")
    folder = Path(command["folder"]).resolve(strict=True)
    if not folder.is_dir():
        raise RuntimeError("Worker scratch path must be a directory")
    return token, folder, command["stage"]


def serve(mode, *, idle_seconds=PROTOCOL_IDLE_SECONDS, max_requests=PROTOCOL_MAX_REQUESTS):
    if mode not in {"infer", "cv"}:
        raise RuntimeError("Unknown persistent worker mode")
    reader = ProtocolReader(sys.stdin.fileno())
    model_cache = {} if mode == "infer" else None
    # Preserve a dedicated protocol fd, then route Python and native-library
    # stdout to stderr. Incidental output cannot corrupt the controller reply.
    sys.stdout.flush()
    with os.fdopen(os.dup(sys.stdout.fileno()), "wb", buffering=0) as output:
        os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
        for _ in range(max_requests):
            token = None
            try:
                raw = reader.read(idle_seconds)
                if raw is None:
                    return
                token, folder, stage = protocol_command(raw, mode)
                request = validated_request(folder)
                if mode == "cv":
                    if "torch" in sys.modules:
                        raise RuntimeError("The isolated CV process must not import Torch")
                    {"prepare": prepare, "finish": finish}[stage](folder, request)
                    if "torch" in sys.modules:
                        raise RuntimeError("The isolated CV process must not import Torch")
                else:
                    if "cv2" in sys.modules:
                        raise RuntimeError("The isolated model process must not import OpenCV")
                    infer(folder, request, model_cache=model_cache)
                    if "cv2" in sys.modules:
                        raise RuntimeError("The isolated model process must not import OpenCV")
                reply = dict(id=token, ok=True)
            except Exception as exc:
                # Bound errors before JSON escaping; the ASCII reply remains
                # below 2 KiB even when an exception contains non-ASCII text.
                error = "".join(c if 32 <= ord(c) < 127 else "?" for c in str(exc))[:768]
                reply = dict(id=token, ok=False, error=error)
            sys.stdout.flush()
            output.write(json.dumps(reply, ensure_ascii=True, separators=(",", ":")).encode() + b"\n")
            if not reply["ok"]:
                return  # A failed interpreter is never reused.


if __name__ == "__main__":
    sys.addaudithook(no_network)
    if len(sys.argv) == 3 and sys.argv[1] == "--serve":
        serve(sys.argv[2])
    else:
        folder = Path(sys.argv[1]).resolve()
        request = validated_request(folder)
        {"prepare": prepare, "infer": infer, "finish": finish}[sys.argv[2]](folder, request)
