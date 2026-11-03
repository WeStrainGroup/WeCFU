"""Synthetic regression for sharing one full-image EDT during SAM seed prep."""
import numpy as np
import pytest
from scipy import ndimage as ndi

from wecfu.experiments import segmentation
from wecfu.plate import PlateCircle
from wecfu.segment import SegmentParams
from wecfu.server.sam_worker import cv_seeds


def synthetic_mask(kind):
    mask = np.zeros((23, 23), dtype=np.uint8)
    if kind == "interior":
        mask[7:16, 7:16] = 255
    elif kind == "border":
        mask[:2, :2] = 255  # Nonempty, but entirely outside eligible peak area.
    return mask


@pytest.fixture
def edt_spy(monkeypatch):
    original = ndi.distance_transform_edt
    calls = []

    def spy(foreground, *args, **kwargs):
        distance = original(foreground, *args, **kwargs)
        calls.append((np.array(foreground, copy=True), distance))
        return distance

    monkeypatch.setattr(ndi, "distance_transform_edt", spy)
    return calls, original


@pytest.mark.parametrize("kind,expected", [
    ("interior", [{"x": 11, "y": 11}]), ("border", []), ("empty", []),
])
def test_cv_seeds_computes_edt_once_per_nonempty_mask(monkeypatch, edt_spy, kind, expected):
    calls, _ = edt_spy
    mask = synthetic_mask(kind)
    monkeypatch.setattr(segmentation, "_candidate_mask", lambda *args: mask.copy())
    seeds = cv_seeds(np.zeros((23, 23, 3), dtype=np.uint8),
                     PlateCircle(cx=11, cy=11, r=10),
                     SegmentParams(peak_min_distance=3, min_area_frac=0))
    assert seeds == expected
    assert len(calls) == (0 if kind == "empty" else 1)
    if calls:
        np.testing.assert_array_equal(calls[0][0], mask > 0)


@pytest.mark.parametrize("kind", ["interior", "border", "empty"])
def test_shared_distance_is_the_computed_array_and_legacy_wrapper_keeps_labels(edt_spy, kind):
    calls, original_edt = edt_spy
    mask = synthetic_mask(kind)
    params = SegmentParams(peak_min_distance=3)
    labels, count, distance = segmentation._component_watershed_split_with_distance(mask, params)
    if kind == "empty":
        assert distance is None and calls == []
    else:
        assert len(calls) == 1 and distance is calls[0][1]
        assert distance.dtype == np.float64
        np.testing.assert_array_equal(distance, original_edt(mask > 0))
    if kind in ("empty", "border"):
        assert count == 0 and not labels.any()
    else:
        assert count == 1
        np.testing.assert_array_equal(labels > 0, mask > 0)
    calls.clear()
    legacy = segmentation._component_watershed_split(mask, params)
    assert isinstance(legacy, tuple) and len(legacy) == 2
    assert legacy[1] == count
    np.testing.assert_array_equal(legacy[0], labels)
    assert len(calls) == (0 if kind == "empty" else 1)
