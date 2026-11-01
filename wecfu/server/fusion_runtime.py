"""Legacy annotation identifiers only; public inference uses Fusion v2.

No private registry, research manifest, weights, or training artifact is read.
"""
from .sam_runtime import RuntimeUnavailable

ENGINE = 'sam_dino_fusion_local_v1'
RECIPE_ID = 'sam_dino_full88_residual12_threshold075_auto095_v1'
ANNOTATION_KIND = 'SAM_D0_plus_box_derived_center_rings'
PLATE_INSET = .95
TIMEOUT_SECONDS = 120.
REASON = 'Legacy Fusion v1 is unavailable in this release; select Fusion v2. No fallback is run.'


def view_for_source(*args, **kwargs):
    raise RuntimeUnavailable(REASON)


class LocalFusionProvider:
    def __init__(self, *, web_mode=False):
        self.enabled = False

    def require_available(self):
        raise RuntimeUnavailable(REASON)

    def capability(self):
        return {'enabled': False, 'available': False, 'reason': REASON,
                'engine': ENGINE, 'label': 'Fusion v1 (legacy)', 'fallback': False}

    def predict(self, *args, **kwargs):
        raise RuntimeUnavailable(REASON)
