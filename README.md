# WeCFU

Friendly, browser-based **CFU (colony-forming unit) counter** for petri-dish photos.
Drag images in, get auto-counted plates with each colony numbered, click-review
(add / delete), then export a CSV.

WeCFU is the *software* half of a full imaging pipeline; the *hardware* half —
an overhead USB camera with integrated lighting plus a 3D-printed petri-dish
jig — is documented (with the printable model and purchase link) in
[`hardware/`](hardware/).

## Three ways to use

### 1. Browser, no install ✨

**https://huggingface.co/spaces/WeCFU/wecfu**

Just open the link. Each visitor gets a private session (≤ 100 images / 400 MB,
auto-cleaned after 1 h of inactivity).

### 2. Local install via conda

```bash
conda install westraingroup::wecfu
wecfu serve
```

No image limits, fully offline. Detailed walkthrough in [USAGE.md](USAGE.md);
other install methods (fresh env, pip wheel, source clone) in
[INSTALL.md](INSTALL.md).

### 3. Command line, for batch jobs

```bash
wecfu batch /path/to/plate/photos --out /path/to/results
```

Produces `results.csv` plus an annotated overlay per image.

## Using the GUI

- **Drop** image files or a folder onto the left side. Files are uploaded (or
  symlinked in local mode) — your originals are never modified.
- **Count all** runs the algorithm on every image. Opening an un-counted image
  also auto-runs once, so the "drop and click around" flow Just Works.
- On any image:
  - **Left-click** empty plate area → add a manual colony (green).
  - **Right-click** a circle → delete it.
  - **Cmd / Ctrl-Z** → undo. **← / →** → previous / next image.
  - **Wheel** → zoom. **Cmd / Ctrl-drag** → pan.
- Pick a colour **preset** (white / cream / yellow / any), or tune the seven
  algorithm parameters by hand. Tick **Live threshold preview** to see in real
  time which pixels are being treated as colonies.
- Sidebar dot states: **grey** = not counted, **blue** = counted, **green** =
  viewed or edited.
- **Export CSV** writes the slim 5-column table; **Export bundle** writes a
  zip with the CSV, annotated overlay PNGs, and a JSON state file per image.

## CSV columns

| column | meaning |
| --- | --- |
| `filename` | the source image |
| `total_count` | final colony count after any human edits |
| `machine_count` | what the algorithm produced on its most recent run |
| `n_removed` | machine detections the user deleted |
| `n_added` | manual detections the user added |
| `notes` | per-image free-text note from the GUI |

`total_count = machine_count − n_removed + n_added`.

## Algorithm

A single classical-CV pipeline; no deep-learning dependency, no GPU.

1. **Plate localisation.** `cv2.HoughCircles` on a downsampled grey image,
   with a largest-circular-contour fallback if Hough finds nothing.
2. **ROI mask.** Disk of radius `plate_inset · r` (default 0.82) — drops the
   glass rim and the agar-glass glare ring.
3. **White-colony gate.** HSV: keep pixels with `V ≥ Min value` (default 200)
   and `S ≤ Max saturation` (default 60). Bright, near-white colonies pass;
   yellow agar streaks don't.
4. **Cleanup.** Morphological open then close to remove specks and fill
   saturated-highlight holes at colony centres.
5. **Touching-colony split.** Distance transform + watershed seeded by
   `peak_local_max` with `min_distance = Peak min distance` (default 15 px).
6. **Shape filter.** Area ∈ [`Min area frac`, max_area_frac] × plate-area,
   circularity ≥ `Min circularity` (0.55), solidity ≥ 0.80, eccentricity ≤ 0.88.

All seven parameter names match the GUI labels one-for-one.

## Parameter cheat-sheet

| Slider | Range | When to nudge it |
| --- | --- | --- |
| Min value       | 0–255       | Empty plate over-counting? Raise. Real colonies missed? Lower. |
| Max saturation  | 0–255       | Want to include yellow / orange colonies? Raise. Yellow agar bleed counted? Lower. |
| Plate inset     | 0–1         | Rim glare counted? Lower (e.g. 0.78). |
| Min circularity | 0–1         | Tighten to filter irregular debris; loosen to keep oddly-shaped colonies. |
| Min area frac   | small float | Tiny pinpoint colonies missed? Lower. Specks counted? Raise. |
| Peak min distance | px        | Touching colonies merged? Lower. One colony split in two? Raise. |

The bottom row of the params bar has two UI helpers that don't affect counts:

| Field | What it does |
| --- | --- |
| New colony radius   | Size (in pixels) of the green circle drawn when you left-click to add a manual colony. Visual only. |
| Live threshold preview | While ticked, the canvas overlays a green tint on every pixel currently passing the `Min value` / `Max saturation` gate, so you can see what the algorithm "sees" before clicking *Apply and recount*. |

## Project layout

```
WeCFU/
├── wecfu/
│   ├── plate.py          # plate detection
│   ├── segment.py        # CV pipeline
│   ├── naming.py         # filename metadata parser
│   ├── pipeline.py       # orchestration
│   ├── overlay.py        # annotated-image rendering
│   ├── cli.py            # 'wecfu batch / serve / web' entrypoints
│   └── server/
│       ├── app.py        # FastAPI routes (single-user + web mode)
│       ├── web.py        # per-visitor session middleware (web mode)
│       └── static/       # vanilla HTML + JS + CSS frontend
├── hardware/             # 3D-printed petri-dish jig + build notes
│   ├── README.md
│   ├── model.3mf
│   └── preview.png
├── Dockerfile            # Hugging Face Spaces image
├── meta.yaml             # conda-build recipe
├── pyproject.toml        # pip / wheel build
└── tests/
```

## Citing

*To be added once the accompanying paper is published.*

## Authors

- Jianghua Zhang (张江华) — `zhangjianghua@westlake.edu.cn`
- Xinyu Wang (王欣宇) — `wangxinyu30@westlake.edu.cn`
- Wenhao Zhou (周文浩) — `zhouwenhao@westlake.edu.cn`
- Zhanyi Zhu (朱展翼) — `zhuzhanyi@westlake.edu.cn`

## License

MIT — see [LICENSE](LICENSE).
