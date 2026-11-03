"""Synthetic screen/export source-palette contract; no models or real images."""
import io
from pathlib import Path
import zipfile

import cv2
import numpy as np
from fastapi.testclient import TestClient

from wecfu.overlay import render
from wecfu.plate import PlateCircle
from wecfu.segment import Detection
import wecfu.server.app as server


ROOT = Path(__file__).resolve().parents[1]
MACHINE_RGB = (183, 131, 150)
MANUAL_RGB = (117, 149, 166)
BACKGROUND_BGR = (10, 20, 30)
MARKS = [Detection(id=1, cx=100, cy=130, r=20, source='cv'),
         Detection(id=2, cx=220, cy=130, r=20, source='manual')]
PLATE = PlateCircle(160, 120, 110)


def expected_bgr(rgb):
    return tuple(round(.9*color+.1*background) for color, background in zip(rgb[::-1], BACKGROUND_BGR))


def assert_colors(image, offset_x=0, offset_y=0):
    for mark, rgb in zip(MARKS, (MACHINE_RGB, MANUAL_RGB)):
        # Four fully covered stroke positions, clear of the labels/banner.
        for x, y in ((mark.cx-mark.r,mark.cy),(mark.cx+mark.r,mark.cy),
                     (mark.cx,mark.cy-mark.r),(mark.cx,mark.cy+mark.r)):
            assert tuple(image[int(y-offset_y),int(x-offset_x)]) == expected_bgr(rgb)


def test_screen_and_synthetic_export_share_source_rgb_alpha_and_solid_marks():
    javascript = (ROOT/'wecfu/server/static/app.js').read_text()
    function = javascript.split('function paintColonyMark(', 1)[1].split('\nfunction paint()', 1)[0]
    assert "detection.source === 'manual' ? 'rgba(117,149,166,0.9)' : 'rgba(183,131,150,0.9)'" in function
    assert 'ctx.setLineDash([])' in function
    source = np.full((240,320,3), BACKGROUND_BGR, dtype=np.uint8); before = source.copy()
    output = render(source, MARKS, PLATE, crop=False, show_plate=False)
    assert_colors(output)
    assert np.array_equal(source, before)
    assert np.array_equal(output[180,160], source[180,160])
    assert [(m.cx,m.cy,m.r,m.source) for m in MARKS] == [(100,130,20,'cv'),(220,130,20,'manual')]


def test_overlay_endpoint_and_zip_export_keep_saved_source_palette(tmp_path,monkeypatch):
    root = tmp_path/'workspace'
    monkeypatch.setattr(server,'detect_plate',lambda pixels:PLATE)
    application = server.build_app(lambda:root)
    source = np.full((240,320,3), BACKGROUND_BGR, dtype=np.uint8)
    ok, encoded = cv2.imencode('.png',source); assert ok; raw=encoded.tobytes()
    with TestClient(application) as client:
        response=client.post('/api/upload',data={'batch':'palette','view':'main'},files={'files':('synthetic.png',raw,'image/png')})
        assert response.status_code==200
        base='/api/batch/palette/image/synthetic.png'
        state=client.post(base+'/initialize',json={'mode':'auto'}).json()
        state.update(detections=[m.asdict() for m in MARKS],counted=True,
                     machine_count_initial=1,count_engine='baseline')
        server._save_state(root,'palette','synthetic.png',state)
        before=server._det_path(root,'palette','synthetic.png').read_bytes()
        response=client.get(base+'/overlay'); assert response.status_code==200
        overlay=cv2.imdecode(np.frombuffer(response.content,np.uint8),cv2.IMREAD_COLOR)
        # Crop origin is max(0, cx-r-24)=26, max(0,cy-r-24)=0.
        assert_colors(overlay,26,0)
        exported=client.get('/api/batch/palette/export.zip'); assert exported.status_code==200
        with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
            image_names=[n for n in archive.namelist() if n.startswith('overlays/')]
            assert image_names==['overlays/synthetic.png.png']
            zipped=cv2.imdecode(np.frombuffer(archive.read(image_names[0]),np.uint8),cv2.IMREAD_COLOR)
            assert np.array_equal(zipped,overlay)
        assert server._det_path(root,'palette','synthetic.png').read_bytes()==before
        assert (root/'inputs/palette/synthetic.png').read_bytes()==raw
