# WeCFU imaging hardware

The physical setup we use to take the petri-dish photos that WeCFU then
counts. Anyone can replicate it: a single 3D-printed base + an
off-the-shelf photo light box + any phone camera.

<p align="center"><img src="preview.png" width="320" alt="rendered preview of the printed base" /></p>

## Bill of materials

| Part | Role | Where |
| --- | --- | --- |
| Photo light box with built-in LEDs and a top viewport (~¥150 / $30) | Diffused, even illumination · acts as the dark background | Any Taobao / Amazon listing for "photo light box" / "拍摄灯箱" around 40 × 40 × 40 cm works |
| 3D-printed base — [`model.3mf`](model.3mf) | Holds a 90 mm petri dish in a fixed, repeatable position under the camera | Print yourself, settings below |
| Phone or webcam | The actual camera | Any modern phone works; we use a regular iPhone |

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

1. Print the base, place it inside the light box, roughly centered.
2. Mount your phone in the top viewport of the light box, lens looking down
   at the petri-dish recess.
3. Slide a 90 mm petri dish into the recess (through the front cutout or
   from above).
4. Take a top-down photo. Repeat for each plate. Use a tripod / clip mount
   for the phone so the framing stays constant across photos.

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
