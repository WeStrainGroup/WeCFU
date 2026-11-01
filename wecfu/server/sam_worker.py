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
from pathlib import Path
import resource
import sys

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
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
    from wecfu.experiments.segmentation import _candidate_mask, _component_watershed_split
    roi = plate.mask(im.shape[:2], shrink=params.plate_inset)
    bw = _candidate_mask(im, roi, params, 5, 9)
    labels, _ = _component_watershed_split(bw, params)
    distance = ndi.distance_transform_edt(bw > 0)
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


def infer(folder, request):
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

    model = build_sam.build_sam2("configs/sam2.1/sam2.1_hiera_t.yaml", str(CHECKPOINT),
                                 device=SAM_DEVICE, apply_postprocessing=False)
    model.eval()
    if next(model.parameters()).dtype != torch.float32:
        raise RuntimeError("SAM2 model must remain float32")
    points = np.array([[s["x"] / prepared["width"], s["y"] / prepared["height"]]
                       for s in prepared["seeds"]], dtype=np.float32).reshape(-1, 2)
    generator = BoundedGenerator(model, **MODEL_SETTINGS, point_grids=[points])
    memory_check()
    with torch.inference_mode():
        annotations = generator.generate(image)
    if SAM_DEVICE == "mps": torch.mps.synchronize()
    memory_check()
    save(folder, "annotations.json", annotations)


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


if __name__ == "__main__":
    sys.addaudithook(no_network)
    folder = Path(sys.argv[1]).resolve()
    request = load(folder, "request.json")
    if (request.get("engine") != ENGINE or request.get("recipe_id") != RECIPE_ID
            or request.get("model_sha256") != MODEL_SHA256):
        raise RuntimeError("Worker recipe mismatch")
    {"prepare": prepare, "infer": infer, "finish": finish}[sys.argv[2]](folder, request)
