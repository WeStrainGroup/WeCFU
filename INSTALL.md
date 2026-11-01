# Install and run WeCFU 1.2.0

## Full local installation: Fusion v2 and the review interface

Use Python 3.12 in a dedicated environment. The fixed model runtime checks for
Python 3.12; the core application alone supports Python 3.10+. Model execution supports Linux CPU and macOS (Apple MPS or explicitly selected
CPU). Windows supports the core interface and classical/manual methods; the
current model process monitor requires Linux or macOS. A failed
model operation is reported, with no automatic change of device or algorithm.

```sh
conda create -n wecfu -c westraingroup -c conda-forge python=3.12 pip wecfu=1.2.0 -y
conda activate wecfu
```

On **Linux CPU systems**, install the official CPU-only PyTorch wheels first:

```sh
python -m pip install --index-url https://download.pytorch.org/whl/cpu torch==2.14.1 torchvision==0.29.1
```

Then, on Linux or macOS, install the matching release's model extras and
prepare its verified model cache:

```sh
python -m pip install "wecfu[models] @ https://github.com/WeStrainGroup/WeCFU/releases/download/v1.2.0/wecfu-1.2.0-py3-none-any.whl"
python -m wecfu.setup_models
python -m wecfu.setup_models --check --runtime-check
wecfu serve
```

The direct wheel URL is intentional: it selects this project's GitHub release
and installs the same application version with its optional model dependencies.
No PyPI publication of WeCFU is required. Setup obtains about 1.36 GB of weights
from their fixed official sources, plus the small tokenizer/source files. Allow
several additional GB for dependencies and installation caches. Keep setup
connected to the internet until it completes. Model inference itself uses the
local cache and does not upload photographs to an inference service.

The browser opens `http://127.0.0.1:8765`. `wecfu serve` preserves its local
`./data` workspace across restarts. To select another workspace or avoid opening
a browser automatically:

```sh
wecfu serve --root /path/to/workspace --no-open
```

On Windows, use Anaconda Prompt. Importing files by drag and drop is supported;
local-path ingestion falls back to copying when symlinks are unavailable.

## Core application without model downloads

```sh
conda create -n wecfu-core -c westraingroup -c conda-forge python=3.12 wecfu=1.2.0 -y
conda activate wecfu-core
wecfu serve
```

This installs the interface, manual tools and explicitly selected classical
methods. Default Fusion v2 remains unavailable until the model runtime and
assets are installed. Its unavailability does not silently switch your chosen
method or overwrite saved results.

## Install from a source checkout

```sh
git clone https://github.com/WeStrainGroup/WeCFU.git
cd WeCFU
git checkout v1.2.0
conda create -n wecfu-source -c conda-forge python=3.12 pip -y
conda activate wecfu-source
python -m pip install '.[models,dev]'
python -m wecfu.setup_models
wecfu serve
```

On a Linux CPU-only installation, install the two CPU wheels shown above before
the extras command. Do not use `pip install sam2`: the supported SAM source is
obtained at the exact revision by WeCFU's setup command.

## Model cache and offline operation

Set `WECFU_MODEL_HOME` to select the shared model cache before running setup and
the application. The default cache is `~/Library/Caches/WeCFU/models` on macOS
and `$XDG_CACHE_HOME/wecfu/models` (normally `~/.cache/wecfu/models`) on Linux.
The application reports an unavailable model if a required file is absent or
has a different checksum. Setup refuses to overwrite a mismatched existing file.

```sh
python -m wecfu.setup_models --cache-dir /path/to/model-cache
python -m wecfu.setup_models --cache-dir /path/to/model-cache --check
```

When using `--cache-dir`, also configure `WECFU_MODEL_HOME` to that directory for
subsequent application runs. For an offline machine, transfer the verified model
cache and install the pinned Python dependency wheels in advance, then run
`--check` there. No input images or results belong in the model cache.

`WECFU_MODEL_PYTHON` can select the Python interpreter holding model dependencies;
`WECFU_CV_PYTHON` can select the classical image-processing interpreter. Both
default to the application's Python. `WECFU_SAM_DEVICE=cpu` explicitly requests
CPU processing; `mps` requires a working Apple MPS device. Restart the application
after changing these settings. `WECFU_ENABLE_FUSION_V2=0` explicitly disables the
fusion option.

## Count and review

Declare the imported photo's view and check the medium boundary before a model
request. Fusion v2 supports declared front/empty views; it rejects reverse or
undeclared views. For an existing workspace image, use **More → Photo type**
(**更多 → 照片类型**) to set or correct its declaration. This changes metadata
only; it does not recount the image, replace saved markings, or confirm a human
reference. Classical/manual methods can also be selected explicitly.
Model candidates only replace markings when you apply
them. Review corrections before exporting; ordinary saves do not create an
independent human-reference annotation.

The local batch command uses the classical pipeline:

```sh
wecfu batch /path/to/photos --out /path/to/results
```

## Troubleshooting

- **Model unavailable:** run `python -m wecfu.setup_models --check --runtime-check` in the active
  environment, confirm the `models` extra is installed, and check the cache path.
- **Unsupported Python:** create the Python 3.12 environment above; do not relax
  dependency pins to make an older interpreter install the model stack.
- **Model error or timeout:** the interface shows the failure without returning
  a partial or substituted count. Saved markings remain intact. Check the
  specific error and available memory before trying again.
- **Old appearance in an already open tab:** reload the page after upgrading and
  restarting the service.
- **Hosted session:** export before leaving. The Hugging Face workspace is
  temporary and separate from local workspaces.

Public sources, fixed model identities and upstream notices are documented in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Development validation uses
synthetic workspaces; it should not use or alter a user's working directory.
