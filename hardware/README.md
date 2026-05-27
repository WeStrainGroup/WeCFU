# WeCFU imaging hardware

The physical setup we use to take the petri-dish photos that WeCFU then
counts. Anyone can replicate it: a single 3D-printed base + one
off-the-shelf overhead camera.

<p align="center"><img src="preview.png" width="320" alt="rendered preview of the printed base" /></p>

<!--
Real-photo gallery — drop the JPEGs into hardware/photos/ and uncomment.
   <p align="center">
     <img src="photos/rig.jpg"   width="46%" alt="assembled rig" />
     <img src="photos/plate.jpg" width="46%" alt="petri dish in the recess" />
   </p>
-->

## Bill of materials

| Part | Role | Where we got ours |
| --- | --- | --- |
| **Hikvision overhead USB camera** (the kind used for warehouse "unboxing / packaging" video — built-in LED ring, integrated downward arm, UVC USB) | Top-down camera + even lighting, all in one unit; no separate light box needed | [Taobao listing](https://e.tb.cn/h.R4RM1f1qXuy5tLE) (~¥150) — search "海康威视 拆包/打包摄像头" for current equivalents |
| **3D-printed base** — [`model.3mf`](model.3mf) | Holds a 90 mm petri dish in a fixed, repeatable position under the camera | Print yourself, settings below |
| **Laptop or PC** with a USB port | Receives the video stream and saves still photos (e.g. via Photo Booth on macOS or the Windows Camera app) | Any |

## Printing the base

| | |
| --- | --- |
| Source file | [`model.3mf`](model.3mf) (single body, no supports, single material) |
| Outer dimensions | 160 × 230 × 95 mm |
| Petri-dish recess | Ø 88.5 mm (standard 90 mm dish) at position (107, 52) from the front-left corner of the top face |
| Side cutout | Rectangular slot through the front so a dish can slide in/out without lifting |
| Triangle count | 334 — trivial, prints anywhere |
| Recommended material | PLA or PETG (this is a static mount, no thermal load) |
| Layer height | 0.2 mm |
| Infill | 15–20 % is plenty |
| Supports | Not needed |
| Print orientation | Top face up (so the petri-dish recess is the top of the print) |
| Estimated time / filament | ~9 h / ~120 g on a typical FDM printer |

`model.3mf` is a "clean" 3MF (mesh only, no embedded slicer settings) — load it in
PrusaSlicer / Bambu Studio / Cura / OrcaSlicer and slice with your printer's
own profile.

## Assembly

1. Plug the Hikvision camera into your laptop via USB; verify it shows up
   as a standard webcam.
2. Set the 3D-printed base on a flat dark surface, directly under the
   camera's downward arm. Centre it so the petri-dish recess is in frame.
3. Slide a 90 mm petri dish into the recess (through the front cutout or
   drop it in from above).
4. Take a top-down still using your OS's camera app. Repeat for each plate.
   The base + camera arm together guarantee identical framing across photos.

Once everything is in position the camera arm and base shouldn't move — that
constant framing is what lets WeCFU treat every photo the same way.

## Photo conventions for WeCFU

The WeCFU software is tuned for:

- **Top-down** view, the whole plate inside the frame, plate centred-ish
- **Dark background** around the plate (the light-box interior provides this)
- **Even lighting** (the box's LED panels handle this)
- Image resolution **≥ 1500 × 1500 px** (any modern phone in default mode is fine)
- Save as JPG or PNG; either works

Filename convention is optional but lets WeCFU group results automatically
across replicates — see [USAGE.md](../USAGE.md) for the suggested pattern.

## End-to-end pipeline

```
  petri dish + light box + 3D base
                ↓  (top-down photo)
            *.jpg
                ↓  (drag-drop or "wecfu serve")
              WeCFU      ←   https://huggingface.co/spaces/WeCFU/wecfu
                ↓                    or  conda install westraingroup::wecfu
        results.csv  +  annotated overlays
```

The 3D-printed base is **the only custom part** — everything else is
either commercial-off-the-shelf or open-source software.

## Reproducibility note

Only the printable `model.3mf` is preserved; the original parametric CAD
project (with sketch history) was lost. The mesh is enough to
re-print or to re-derive a parametric model from, since the design is
just one cuboid + one cylindrical cutout + one rectangular cutout. If
you want to modify the design, the easiest path is **Fusion 360 →
Insert mesh → Convert to BRep**; the 334-triangle mesh converts in
seconds and becomes fully editable.
