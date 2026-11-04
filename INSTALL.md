# Install and run WeCFU 1.2.2

## Local installation

This release requires **Python 3.12**, including Lite/Custom-only installations. Ultra runs on Linux CPU or
macOS CPU/MPS. Windows supports Lite, Custom and manual marking; Ultra is not
supported there. CUDA is not a supported device setting.

```sh
conda create -n wecfu -c westraingroup -c conda-forge python=3.12 wecfu=1.2.2 -y
conda activate wecfu
wecfu serve
```

On macOS and Linux, the first `wecfu serve` prepares Ultra before opening the
page. It installs pinned model dependencies in a separate environment inside
the user model cache, obtains official SAM source at a fixed revision, and
downloads the approximately **156 MB SAM checkpoint**. It verifies the files
and runtime, then starts the application. Allow additional space for the
Python environment and installation caches. This first setup needs internet
access; later launches reuse the verified environment and files. You do not
need a separate model-wheel installation in the Conda environment.

If setup fails, the terminal reports the reason. The app can still run Lite
and Custom; it does not replace an Ultra request with a Lite result. Retry
`wecfu serve` after fixing the reported download or runtime problem.

The browser opens `http://127.0.0.1:8765`. Import photos and choose **Recognize
all** or **Recognize current**; importing alone does not run recognition.
The first page is in English. The app remembers a choice of English, Simplified
Chinese, French or Russian.

## Temporary and persistent work

Normal startup creates a fresh, empty session. Refreshing the page keeps that
session. Closing a browser tab does not stop the local server. Stop the server
with **Ctrl-C in its terminal** to clear that session’s imported files/links
and counting records. Export needed results before stopping. Original source
photos are not deleted.

To keep work across server restarts, choose a workspace explicitly:

```sh
wecfu serve --root /path/to/workspace --no-open
```

Older `./data` workspaces are left intact but are not loaded automatically. Open
one explicitly with `--root` if you want to resume it. A new version does not
rerun its saved counts automatically.

## Upgrade an existing installation

Export important results and stop the old server before upgrading. Installing
a new package does not update an already running process.

```sh
conda activate wecfu
conda install -c westraingroup -c conda-forge python=3.12 wecfu=1.2.2 -y
wecfu serve
```

The startup checks and reuses the model cache. No extra pip install is needed.
Reload the browser after the new server starts. To resume a persistent
workspace, pass its existing `--root`; do not delete it to upgrade.

## Offline startup and manual setup

To skip automatic model preparation:

```sh
wecfu serve --no-model-setup
```

Lite and Custom remain available. Ultra needs a previously prepared runtime
and verified assets; skipping setup does not make missing models available.
On Windows, use Anaconda Prompt. Drag-and-drop import is supported; path import
copies files when symbolic links are unavailable.

The standalone asset tool now prepares **SAM only** by default:

```sh
python -m wecfu.setup_models
python -m wecfu.setup_models --check --runtime-check
```

`--check` verifies the selected cached assets without downloading them.
`--runtime-check` also checks the model interpreter and device. A new process
automatically finds the prepared runtime in the selected model cache, so this
check also works after stopping and reopening your terminal. An explicit
`WECFU_MODEL_PYTHON` takes precedence. The asset tool does not install the model runtime; normal `wecfu serve` handles
that setup. Advanced users retaining the old Fusion environment can request
its full asset set explicitly with `--profile all`.

For an offline machine, prepare and verify the cache and runtime on a
compatible system first. Copying just the SAM checkpoint is insufficient.
Do not store photographs or results in the model cache.

## Install from source

```sh
git clone https://github.com/WeStrainGroup/WeCFU.git
cd WeCFU
git checkout v1.2.2
conda create -n wecfu-source -c conda-forge python=3.12 pip -y
conda activate wecfu-source
python -m pip install '.[dev]'
wecfu serve
```

The same automatic model preparation applies. Maintainers building a managed
runtime can install the pinned `models` extra instead; Linux CPU installations
should use the official CPU PyTorch wheels specified in the Dockerfile. Do not
install an unrelated `sam2` package: WeCFU verifies its supported official
source revision.

## Cache, device and worker settings

`WECFU_MODEL_HOME` selects the model cache. The default is
`~/Library/Caches/WeCFU/models` on macOS and `$XDG_CACHE_HOME/wecfu/models`
(normally `~/.cache/wecfu/models`) on Linux. Existing files with incorrect hashes
are rejected rather than silently overwritten.

```sh
python -m wecfu.setup_models --cache-dir /path/to/model-cache
python -m wecfu.setup_models --cache-dir /path/to/model-cache --check
```

When using `--cache-dir`, set `WECFU_MODEL_HOME` to that directory for application
runs as well.

- `WECFU_MODEL_PYTHON` can select an explicitly managed model interpreter;
  otherwise startup uses the prepared runtime. `WECFU_CV_PYTHON` can select the
  image-processing interpreter.
- `WECFU_SAM_DEVICE=cpu` explicitly selects CPU. During normal startup, macOS
  chooses MPS when it is available, otherwise CPU; Linux uses CPU. An explicit
  device setting is respected and reports an error if unavailable. A failed
  recognition request is not rerun automatically on another device.
- Warm SAM workers are enabled by default. They keep the model loaded between
  requests; every photograph is processed anew. Workers retire after idle time
  or a bounded number of requests. `WECFU_SAM_WARM_WORKER=0` selects the
  cold-process route without changing recognition rules.

Restart the server after changing these settings. Runtime depends on the
computer and photos; no universal minimum RAM or throughput is established.
Lite is available when model execution is unsupported or too demanding.

## Recognition and export

Ultra and Lite batch recognition preserve existing results. Ultra previews an
existing photo’s replacement before adoption; a new untouched photo can be
recognized and saved directly. Custom applies traditional-algorithm settings
and can recount machine-only results, while skipping protected manual work in
a batch. See [USAGE.md](USAGE.md) for controls and exports.

The command-line batch command remains a separate classical pipeline:

```sh
wecfu batch /path/to/photos --out /path/to/results
```

## Troubleshooting

- **Ultra unavailable:** read the terminal setup error. Confirm Python 3.12,
  the cache location and the selected device, then restart `wecfu serve`.
  Use `python -m wecfu.setup_models --check --runtime-check` to inspect the
  prepared assets and runtime.
- **MPS unavailable:** set `WECFU_SAM_DEVICE=cpu` and restart, or choose Lite.
- **Model error or timeout:** a failed request does not substitute a different
  count; existing marks remain intact. Batch reports distinguish completed,
  skipped and failed photos.
- **Imported photos have no counts:** choose **Recognize all** in the sidebar.
- **Old page or photos after upgrading:** stop the old server, start the new
  one, and reload the page. Explicit persistent workspaces retain their files.
- **Hosted session:** Ultra, Lite and Custom use the same mode selection as the
  local app. Photos are uploaded to its temporary server workspace; export
  before leaving.

See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for sources and licenses.
Development acceptance checks should use an isolated workspace, not an active
user’s working directory.
