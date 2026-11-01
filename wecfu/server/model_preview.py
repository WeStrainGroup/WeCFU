"""Local/offline model inference and workspace-owned ephemeral candidates.

This module never writes editable states, images, references, or model files.
The API owns per-image locking and atomic adoption. One process-wide inference
slot protects OpenCV Net operations and rejects overlapping work instead of
building an unbounded queue. Candidate storage has a fixed count limit and TTL.
"""
from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import threading
import time
from uuid import uuid4

from . import sam_runtime, fusion_runtime, fusion_runtime_v2, runtime_diagnostics

ENGINE = "cfucounter_onnx_author_v1"
# Legacy display identifier only; this release does not ship or load that model.
MODEL_SHA256 = "281ddbd3ad3f464a4c1951ea7cc279a4836ab4ffbdd155c58a15ccbec8f23895"
SCORE_THRESHOLD = 0.45
NMS_THRESHOLD = 0.50
_INFERENCE_SLOT = threading.Lock()


class PreviewError(RuntimeError):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code, self.detail = status_code, detail


def state_signature(state: dict) -> str:
    return hashlib.sha256(json.dumps(state, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


class ModelPreviewManager:
    def __init__(self, *, web_mode: bool = False):
        self.sam = sam_runtime.LocalSamProvider(web_mode=web_mode)
        self.fusion = fusion_runtime.LocalFusionProvider(web_mode=web_mode)
        # The public product exposes only the accepted Fusion v2 model.
        self.fusion.enabled = False
        self.fusion_v2 = fusion_runtime_v2.LocalFusionProvider(web_mode=web_mode)
        self.enabled = False  # Legacy saved annotations remain readable; no legacy inference.
        self.model_path = None
        self.ttl_seconds = 300.0
        self.max_candidates = 16
        self._clock = time.monotonic
        self._guard = threading.RLock()
        self._candidates = OrderedDict()
        self._model = None
        self._model_fingerprint = None
        self._checked_fingerprint = None
        self._checked_digest = None

    def _weights(self):
        raise PreviewError(503, "Legacy CFUCounter inference is unavailable; select Fusion v2. No fallback is run.")

    def capability(self) -> dict:
        try:
            self._weights()
            available = True
        except PreviewError:
            available = False
        return {"enabled": self.enabled, "available": available,
                "label": "CFUCounter · experimental preview", "engine": ENGINE,
                "score_threshold": SCORE_THRESHOLD, "nms_threshold": NMS_THRESHOLD}

    def require_available(self):
        return self._weights()

    def predict(self, pixels, plate, plate_inset: float):
        return self._weights()

    def predict_sam(self, payload, plate, image_sha256):
        if not _INFERENCE_SLOT.acquire(blocking=False):
            raise PreviewError(429, "Another local model preview is running; try again when it finishes")
        try:
            return self.sam.predict(payload, plate, image_sha256)
        except sam_runtime.RuntimeUnavailable as exc:
            raise PreviewError(503, runtime_diagnostics.error_detail(exc)) from exc
        except Exception as exc:
            raise PreviewError(503, "Local SAM2 preview failed; no candidate was created") from exc
        finally:
            _INFERENCE_SLOT.release()

    def _prune(self):
        now = self._clock()
        for identifier in list(self._candidates):
            if self._candidates[identifier]["deadline"] <= now:
                del self._candidates[identifier]

    def predict_fusion(self, payload, plate, image_sha256, width, height, view, *, deadline=None, engine=fusion_runtime_v2.ENGINE):
        if not _INFERENCE_SLOT.acquire(blocking=False):
            raise PreviewError(429, "Another local model preview is running; try again when it finishes")
        try:
            if engine not in (fusion_runtime.ENGINE, fusion_runtime_v2.ENGINE):
                raise PreviewError(422, "Unknown fusion engine")
            provider = self.fusion_v2 if engine == fusion_runtime_v2.ENGINE else self.fusion
            return provider.predict(payload, plate, image_sha256, width, height, view, deadline=deadline)
        except fusion_runtime.RuntimeUnavailable as exc:
            try: runtime_diagnostics.preserve_failure(exc, phase="fusion-preview")
            except Exception: pass
            raise PreviewError(503, runtime_diagnostics.error_detail(exc)) from exc
        except Exception as exc:
            try: runtime_diagnostics.preserve_failure(exc, phase="fusion-preview")
            except Exception: pass
            identifier = getattr(exc, "diagnostic_id", "unavailable")
            raise PreviewError(503, "Local fusion preview failed; no partial candidate was created [diagnostic " + identifier + "]") from exc
        finally:
            _INFERENCE_SLOT.release()

    def create_candidate(self, owner: tuple, state: dict, image_sha256: str,
                         model_params: dict, detections: list, raw_count: int, elapsed_ms: float, *, engine: str = ENGINE,
                         fusion_provenance: dict | None = None) -> dict:
        identifier = uuid4().hex
        result = {"candidate_id": identifier, "engine": engine,
                  "base_revision": state.get("revision", 0), "image_sha256": image_sha256,
                  "plate": deepcopy(state["plate"]), "model_params": deepcopy(model_params),
                  "model_sha256": sam_runtime.MODEL_SHA256 if engine == sam_runtime.ENGINE else MODEL_SHA256, "detections": deepcopy(detections),
                  "raw_count": raw_count, "candidate_count": len(detections), "elapsed_ms": elapsed_ms,
                  "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=self.ttl_seconds)).isoformat()}
        if engine == sam_runtime.ENGINE:
            result["recipe_id"] = sam_runtime.RECIPE_ID
        elif engine in (fusion_runtime.ENGINE, fusion_runtime_v2.ENGINE):
            version = fusion_runtime_v2 if engine == fusion_runtime_v2.ENGINE else fusion_runtime
            if fusion_provenance is None:
                raise PreviewError(503, "Fusion candidate lacks complete provenance")
            if fusion_provenance.get("recipe_id") != version.RECIPE_ID:
                raise PreviewError(503, "Fusion candidate version differs from provenance")
            result.update(recipe_id=version.RECIPE_ID,
                          model_sha256=fusion_provenance["model_sha256"],
                          fusion_provenance=deepcopy(fusion_provenance),
                          annotation_kind=version.ANNOTATION_KIND)
        with self._guard:
            self._prune()
            while len(self._candidates) >= self.max_candidates:
                self._candidates.popitem(last=False)
            self._candidates[identifier] = {"owner": owner, "state_signature": state_signature(state),
                                            "deadline": self._clock() + self.ttl_seconds, "result": result}
        return deepcopy(result)

    def candidate(self, identifier: str, owner: tuple) -> dict:
        with self._guard:
            self._prune()
            record = self._candidates.get(identifier)
            if record is None:
                raise PreviewError(410, "Model candidate expired or was evicted; run a new preview.")
            if record["owner"] != owner:
                raise PreviewError(409, "Model candidate belongs to a different image or workspace.")
            return deepcopy(record)
