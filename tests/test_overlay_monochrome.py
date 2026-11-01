"""Synthetic checks for exported marker styling, independent of recognition."""
from __future__ import annotations

import cv2
import numpy as np

from wecfu.overlay import render
from wecfu.plate import PlateCircle
from wecfu.segment import Detection


def test_overlay_keeps_source_and_unannotated_photo_pixels():
    yy, xx = np.indices((280, 480))
    source = np.stack(((xx + 17) % 256, (yy + 83) % 256,
                       (xx + yy + 151) % 256), axis=-1).astype(np.uint8)
    original = source.copy()
    marks = [Detection(1, 100.8, 140.7, 32.5),
             Detection(2, 280.8, 140.7, 32.5, source="manual")]
    records = [d.asdict() for d in marks]
    plate = PlateCircle(240, 140, 125)
    output = render(source, marks, plate, crop=False, show_plate=False)

    assert np.array_equal(source, original)
    assert output.shape == source.shape
    assert not np.shares_memory(source, output)
    assert [d.asdict() for d in marks] == records
    allowed = np.zeros(source.shape[:2], dtype=bool)
    allowed[:50, :140] = True  # Existing count banner and its text.
    for d in marks:
        cx, cy, radius = int(d.cx), int(d.cy), max(int(d.r), 4)
        allowed[cy-radius-5:cy+radius+6, cx-radius-5:cx+radius+6] = True
        tx, ty = int(cx + d.r + 2), int(cy - 2)
        (width, height), baseline = cv2.getTextSize(
            str(d.id), cv2.FONT_HERSHEY_SIMPLEX, .55, 3)
        allowed[ty-height-3:ty+baseline+4, tx-3:tx+width+4] = True
    assert np.array_equal(output[~allowed], original[~allowed])
    assert np.any(output != original)


def test_transparent_marks_have_no_halo_and_keep_source_styles(monkeypatch):
    source = np.full((280, 480, 3), 200, dtype=np.uint8)
    marks = [Detection(1, 100, 140, 32),
             Detection(2, 280, 140, 32, source="manual"),
             Detection(3, 100, 220, 16),
             Detection(4, 280, 220, 16, source="manual")]
    original_blend = cv2.addWeighted
    blends = []

    def record_blend(layer, alpha, current, beta, gamma, **kwargs):
        blends.append((alpha, beta))
        assert not np.shares_memory(layer, current)
        return original_blend(layer, alpha, current, beta, gamma, **kwargs)

    monkeypatch.setattr(cv2, "addWeighted", record_blend)
    output = render(source, marks, PlateCircle(240, 140, 125),
                    crop=False, show_plate=False)
    np.testing.assert_allclose(blends, [(0.9, 0.1), (0.9, 0.1)], rtol=0, atol=1e-12)
    assert not np.array_equal(output[..., 0], output[..., 2]), "Source classes use distinct muted ink colors"
    assert np.all(output[60:] <= 200), "Neither circles nor labels may add a white halo"
    assert np.all(source == 200)

    # Fully covered strokes obey the specified alpha, with OpenCV's 8-bit rounding.
    values = tuple(np.rint(np.array(bgr) * .9 + 200 * .1).astype(np.uint8)
                   for bgr in ([150, 131, 183], [166, 149, 117]))
    angles = np.linspace(0, 2*np.pi, 720, endpoint=False)
    coverage = []
    for mark, value in zip(marks[:2], values):
        xs = np.rint(mark.cx + mark.r*np.cos(angles)).astype(int)
        ys = np.rint(mark.cy + mark.r*np.sin(angles)).astype(int)
        coverage.append(np.mean(np.all(output[ys, xs] == value, axis=-1)))
        area = output[int(mark.cy)-36:int(mark.cy)+37,
                      int(mark.cx)-36:int(mark.cx)+37]
        np.testing.assert_array_equal(area.reshape(-1, 3).min(axis=0), value)
        np.testing.assert_array_equal(area.reshape(-1, 3).max(axis=0), [200, 200, 200])
        tx, ty = int(mark.cx + mark.r + 2), int(mark.cy - 2)
        label = output[ty-16:ty+4, tx:tx+14]
        assert np.any(label < 200), "The source-colored label must remain visible"
        assert np.all(label.reshape(-1, 3).min(axis=0) >= value)
        assert int(label.max()) <= 200
    assert coverage[0] > .9
    assert coverage[1] > .9
    assert coverage[0] == coverage[1], "Both source classes have the same solid geometry"
    assert not np.array_equal(values[0], values[1]), "Color alone distinguishes the two source classes"
