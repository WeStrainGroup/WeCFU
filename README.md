# WeCFU

Friendly, browser-based **CFU (colony-forming unit) counter** for culturomics
plate photos. Drag a folder of plate images into a browser window, get
auto-counted plates with each colony numbered, then click-review (add / delete)
and export a CSV ready for downstream analysis.

**🦠 Try it instantly — no install:** https://huggingface.co/spaces/WeCFU/wecfu

For long-term / offline / large-batch use, install locally — see
[INSTALL.md](INSTALL.md). Built for the WeF culturomics dataset but applies
to any standard top-down glass-petri photo with light colonies on a darker
agar. Small, dependency-light, reproducible — not a black box.

## Quickstart

```bash
# 1. create the env (once)
conda env create -f environment.yml
conda activate wecfu
pip install -e .

# 2. launch the GUI; it opens at http://127.0.0.1:8765
wecfu serve

# 3. (optional) batch-mode for headless use
wecfu batch /path/to/plate/photos --out runs/2026-05-21
```

In the GUI:

- **Drop a folder or files** onto the upload zone (or paste an absolute path
  and click *Ingest path*). The tool **symlinks** rather than copies your
  originals — your source folder is never modified.
- Click **Run all** to auto-detect colonies.
- Click a plate in the left list → it loads in the canvas with each
  detected colony numbered.
- **Left-click** empty space → add a manual colony (cyan).
- **Right-click** a circle → delete it.
- **Cmd/Ctrl-Z** to undo, **← / →** for prev/next image, **Space** to mark reviewed.
- **Cmd/Ctrl-drag** to pan, scroll to zoom.
- Pick a colony-color **preset** (white / cream / yellow / any) or tweak the
  sliders. Tick **live mask preview** to see in real time which pixels are
  being treated as colonies.
- **Export CSV** for just the counts, or **Export bundle (zip)** for CSV +
  annotated overlay PNGs + per-image JSON state.

## Output

For each run under `data/runs/<batch>/`:

- `detections/<stem>.json` — editable state of record (per-colony center,
  radius, accepted, source, reviewed flag, parameters, diagnostics).
- `overlays/<stem>.png` — annotated review image with numbered circles.
- Export → `cfu_<batch>.csv`.

## Algorithm

Two-layer pipeline; both layers operate on a single BGR image.

### Layer 1 — classical CV (default)

1. **Plate localisation.** Downsample to 800 px max side, Gaussian
   median-blur, then `cv2.HoughCircles` for the dish boundary. If that
   fails, fall back to the largest highly-circular contour
   (`circularity ≥ 0.80`) of an Otsu-thresholded binary. Returns
   `(cx, cy, r)`.
2. **ROI mask.** A disk of radius `plate_inset · r` (default `0.82`),
   conservatively inside the agar to avoid the glass rim and the
   agar–glass glare ring.
3. **White-colony gate.** Convert to HSV; keep pixels with
   `V ≥ min_value` (default 200) **and** `S ≤ max_saturation` (default 60)
   inside the ROI. This selects bright, near-white pixels and rejects
   yellow agar streaks or amber media stains.
4. **Cleanup.** Morphological opening (5×5 ellipse) removes specks;
   closing (9×9) fills the small interior holes typical of saturated
   highlights at colony centers.
5. **Touching-colony split.** Distance transform + watershed seeded by
   `skimage.feature.peak_local_max` with `min_distance = 15 px`,
   `threshold_rel = 0.5`. Each watershed basin → one candidate.
6. **Shape filter.** Each basin's largest contour must satisfy
   `min_area_frac ≤ area / plate_area ≤ max_area_frac`,
   `circularity ≥ min_circularity` (0.55),
   `solidity ≥ min_solidity` (0.80),
   `eccentricity ≤ max_eccentricity` (0.88).
7. **Low-confidence flag.** Foreground fraction > 15 % of the plate, or
   many regions rejected for shape with > 5 % foreground → likely
   confluent / swarming → flagged in the UI as `LOW CONF`.

### Layer 2 — SAM fallback (on demand)

For dense/touching plates the user clicks **SAM** on a specific image. We
lazily import `segment_anything` (ViT-B; ~358 MB checkpoint at
`~/.cache/wecfu/sam_vit_b.pth`) and run
`SamAutomaticMaskGenerator` (`points_per_side=48`). The same area /
circularity filter as Layer 1 is applied to SAM's masks. Lazy install:

```bash
pip install segment-anything torch
mkdir -p ~/.cache/wecfu
curl -L https://dl.fbaipublicfiles.com/segment_anything/sam_vit_b_01ec64.pth \
  -o ~/.cache/wecfu/sam_vit_b.pth
```

### Manual layer

Any plate the user touches (add / delete) is marked `reviewed=True` and
skipped on subsequent batch runs (unless `--force`). The CSV records
`n_manual` so manual additions stay auditable; the per-image JSON in the
export bundle records every detection's origin (`cv` / `sam` / `manual`).

## Filename convention

The tool expects:

```
P<plate>V<version>_G[+|-]_<medium>_<dilution>_<aer|ana>_day<N>_<rep>_<YYYYMMDD_HHMMSS>.jpg
```

e.g. `P01V18_G+_YM_1X_aer_day9_1_20260521_162517.jpg`.

If a filename doesn't match, the row still appears in the CSV with empty
metadata columns; counting still works.

## Project layout

```
WeCFU/
├── wecfu/
│   ├── plate.py          # plate detection
│   ├── segment.py        # Layer 1 CV pipeline
│   ├── sam_refine.py     # Layer 2 SAM (lazy)
│   ├── naming.py         # filename parser
│   ├── pipeline.py       # orchestration
│   ├── overlay.py        # rendering
│   ├── cli.py            # CLI entry
│   └── server/
│       ├── app.py        # FastAPI backend
│       └── static/       # vanilla HTML+JS+CSS frontend
├── data/
│   ├── inputs/<batch>/   # symlinks / uploaded images
│   └── runs/<batch>/
│       ├── detections/   # editable JSON state
│       ├── overlays/     # annotated PNGs
│       └── results.csv   # batch-mode aggregate
└── tests/
```

## Calibration tips

- Empty plate counting >0 → raise `min_value` (e.g. 215) or lower
  `plate_inset` (e.g. 0.78) to drop the agar–glass rim ring.
- Real colonies missed → lower `min_value` (e.g. 180) or `min_circularity`
  (e.g. 0.45). Watch for false positives.
- Touching colonies merged into one → lower `peak_min_distance` in the GUI
  rerun, or use SAM.
- Yellow / cream / non-white colonies → raise `max_saturation` (e.g. 120)
  to include them. The white-gate is intentionally strict by default.

## Citing

Please cite as: *WeCFU v0.1 (WeF culturomics, 2026)*. A pre-print
describing the validation set and accuracy is in preparation; see the
upcoming repository release for the BibTeX entry.

## License

MIT.
