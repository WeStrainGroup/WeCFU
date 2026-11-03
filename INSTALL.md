# Install and run WeCFU 1.2.1

## Local installation with Ultra

The application supports Python 3.10+. Ultra's fixed algorithm + SAM runtime
requires **Python 3.12** and its pinned optional dependencies. Ultra currently
runs on Linux CPU or macOS CPU/MPS. Windows supports Lite, Custom and manual
marking; the model process monitor requires Linux or macOS. CUDA is not a
supported device setting.

```sh
conda create -n wecfu -c westraingroup -c conda-forge python=3.12 pip wecfu=1.2.1 -y
conda activate wecfu
```

On **Linux CPU systems**, install the official CPU-only PyTorch wheels first:

```sh
python -m pip install --index-url https://download.pytorch.org/whl/cpu torch==2.14.1 torchvision==0.29.1
```

Then, on Linux or macOS:

```sh
python -m pip install "wecfu[models] @ https://github.com/WeStrainGroup/WeCFU/releases/download/v1.2.1/wecfu-1.2.1-py3-none-any.whl"
python -m wecfu.setup_models
python -m wecfu.setup_models --check --runtime-check
wecfu serve
```

The direct wheel URL installs this release and its optional dependencies; it
does not require a PyPI release. Setup downloads and verifies the fixed public
asset manifest. That manifest currently includes legacy Fusion/DINO assets as
well as SAM: approximately 1.36 GB of weights plus source/tokenizer files.
**Ultra does not run DINO.** Allow additional disk space for Python dependencies
and installation caches. Downloads happen during setup, not during counting.
Model requests use the local cache and do not upload photographs.

The browser opens `http://127.0.0.1:8765`. The local `./data` workspace is preserved
across restarts. To choose a workspace or suppress automatic browser opening:

```sh
wecfu serve --root /path/to/workspace --no-open
```

## Core application without models

```sh
conda create -n wecfu-core -c westraingroup -c conda-forge python=3.12 wecfu=1.2.1 -y
conda activate wecfu-core
wecfu serve
```

Choose **Lite** or **Custom** in the page. Both use traditional image processing
without loading SAM. Manual marking is also available. Ultra remains the local
default selection, but reports unavailable until its dependencies and assets are
installed; it never silently substitutes a Lite result.

On Windows, use Anaconda Prompt for these core commands. Drag-and-drop import is
supported; path import copies files if symbolic links are unavailable.

## Upgrade an existing installation

Export important results and stop the running server before upgrading. Keep the
existing workspace; do not delete it to update the application.

```sh
conda activate wecfu
conda install -c westraingroup -c conda-forge wecfu=1.2.1 -y
```

For an installation with Ultra, also install the matching `1.2.1` model-extra
wheel shown above and run the asset/runtime check. Restart with the same
`--root`, then reload existing browser tabs. Saved counts are not automatically
rerun when the version or selected mode changes.

## Install from source

```sh
git clone https://github.com/WeStrainGroup/WeCFU.git
cd WeCFU
git checkout v1.2.1
conda create -n wecfu-source -c conda-forge python=3.12 pip -y
conda activate wecfu-source
python -m pip install '.[models,dev]'
python -m wecfu.setup_models
wecfu serve
```

On Linux CPU, install the two CPU wheels first. For a core-only source install,
use `python -m pip install '.[dev]'` and skip model setup. Do not use
`pip install sam2`: WeCFU setup obtains the supported SAM source at a fixed
revision.

## Cache, device and worker settings

`WECFU_MODEL_HOME` selects the shared model cache. Its default is
`~/Library/Caches/WeCFU/models` on macOS and `$XDG_CACHE_HOME/wecfu/models`
(normally `~/.cache/wecfu/models`) on Linux. Missing or altered files make a
model unavailable; setup refuses to overwrite a mismatched existing file.

```sh
python -m wecfu.setup_models --cache-dir /path/to/model-cache
python -m wecfu.setup_models --cache-dir /path/to/model-cache --check
```

When using `--cache-dir`, set `WECFU_MODEL_HOME` to the same directory for
application runs. For offline use, transfer a verified cache and install the
pinned dependency wheels in advance, then run `--check` on the target machine.
Do not put photographs or results in the model cache.

- `WECFU_MODEL_PYTHON` selects the interpreter with model dependencies;
  `WECFU_CV_PYTHON` selects the image-processing interpreter. Both default to
  the application's Python.
- `WECFU_SAM_DEVICE=cpu` explicitly selects CPU. macOS defaults to `mps`, which
  requires a working Apple MPS device. Linux defaults to CPU. There is no
  automatic device fallback.
- Warm SAM workers are enabled by default. They retain the loaded model between
  requests, reducing repeated startup work; each photograph is processed anew.
  Workers retire after idle time or a bounded number of requests. Set
  `WECFU_SAM_WARM_WORKER=0` to restore the cold-process route without changing
  recognition rules; `1` explicitly enables warm workers.

Restart the server after changing these settings. Performance depends on the
computer and photos. No universal minimum RAM or throughput is established.
Requests have time and memory limits; these are process safeguards, not a
minimum hardware specification. Lite is available when model execution is
unsupported, too slow or too demanding.

## Count and review

Import photos, then choose **Recognize all** or **Recognize current**. Importing
and opening photos do not run recognition, and no front/blank/back declaration
is required. Accepting a view does not establish accuracy for every view or
colony morphology.

Ultra and Lite batch recognition preserve existing results. Ultra previews an
existing photo's replacement before adoption; new untouched photos can be
recognized and saved directly. Custom uses applied traditional-algorithm
settings and can recount machine-only results, while skipping protected manual
work in a batch. See [USAGE.md](USAGE.md) for controls, protection and exports.

The command-line batch command remains a separate classical pipeline:

```sh
wecfu batch /path/to/photos --out /path/to/results
```

## Troubleshooting

- **Ultra unavailable:** check that the model extra is installed in Python 3.12,
  confirm the cache path, and run `python -m wecfu.setup_models --check --runtime-check`.
- **MPS unavailable:** explicitly select `WECFU_SAM_DEVICE=cpu`, then restart,
  or choose Lite. The app does not change devices on your behalf.
- **Model error or timeout:** inspect the reported error. A failed request does
  not return a substituted count; existing marks remain intact. A batch reports
  completed, skipped and failed photos separately.
- **Imported photos have no counts:** import only adds them. Choose
  **Recognize all** in the sidebar.
- **Old page after upgrading:** restart the server, then reload the browser tab.
- **Hosted session:** the hosted app defaults to the web classical workflow;
  Detailed check can explicitly preview SAM for one photo when available.
  Uploads go to its server and the workspace is temporary; export before leaving.

See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for public sources and
licenses. Development acceptance checks should use an isolated workspace,
not an active user's working directory.
