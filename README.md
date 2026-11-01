# WeCFU 1.2.0

A browser workspace for counting colonies on petri-dish photographs, reviewing
individual markers, and exporting counts with annotated images.

The default automatic workflow uses **Fusion v2**: SAM 2.1 segmentation plus a
colony Grounding DINO detector and a fixed candidate filter. Custom classical
image-processing methods and fully manual marking remain available. If the
selected model cannot run, WeCFU reports the problem; it does not substitute a
classical count.

## Use online

Open [WeCFU on Hugging Face](https://huggingface.co/spaces/WeCFU/wecfu).
The container includes the pinned CPU model runtime and verified assets. A cold
start or model request can take time; keep the page open until it completes.
Each visitor has a separate temporary workspace, limited to 100 images and
400 MB. Export your results before leaving: inactive workspaces are removed
after approximately one hour, and a Space restart can remove them sooner.

Photos uploaded to the hosted app are processed on that server. WeCFU does not
send them to an external inference API. Local installation keeps processing
and working files on your computer.

## Install locally with Fusion v2

Use a Python 3.12 environment. The Conda package provides the core application;
the release wheel's `models` extra installs the pinned model runtime.

```sh
conda create -n wecfu -c westraingroup -c conda-forge python=3.12 pip wecfu=1.2.0 -y
conda activate wecfu
python -m pip install "wecfu[models] @ https://github.com/WeStrainGroup/WeCFU/releases/download/v1.2.0/wecfu-1.2.0-py3-none-any.whl"
python -m wecfu.setup_models
wecfu serve
```

Setup downloads about 1.36 GB of fixed model weights, plus source/tokenizer
files, and verifies their sizes and SHA-256 checksums. Python dependencies
require additional disk space. Downloads happen during setup, not while a
photograph is being counted. See [INSTALL.md](INSTALL.md) for Linux CPU wheels,
core-only installation, offline cache verification and troubleshooting.

## Review and export

1. Import plate photos. Declare whether they show the front of the plate, an
   empty plate, or the reverse side. Fusion v2 accepts front/empty views;
   reverse or undeclared views require a different explicitly selected workflow.
2. Check the detected medium boundary. Choose default automatic recognition,
   a custom method, or manual marking. Opening a photo alone does not run a model.
3. Review model candidates before applying them. Add missing colonies, remove
   incorrect markers, and use undo while reviewing. Model failures leave saved
   markings unchanged.
4. Export CSV or a ZIP with the CSV, annotated images and per-image state.
   Local workspaces persist when `wecfu serve` restarts; web workspaces are
   temporary. Exported counts reflect your saved corrections.

The light interface includes keyboard navigation, zoom/pan, adjustable marker
size, default/custom controls and a collapsible export area. Standard keyboard
shortcuts include Cmd/Ctrl-Z for undo and left/right arrows to change images.

Model output is a proposal for human review. This release does not establish
accuracy across all organisms, media, imaging setups or growth patterns. Marker
circles are review aids and should not be treated as exact segmentation outlines.

## Command line

```sh
wecfu batch /path/to/plate/photos --out /path/to/results
```

The batch command explicitly uses the classical pipeline. It does not invoke
Fusion v2 or replace a requested model run.

## Development and releases

- [Installation and operation](INSTALL.md)
- [Release and deployment procedure](SHARE.md)
- [Changes in 1.2.0](CHANGELOG.md)
- [Imaging hardware](hardware/): the previously published camera/jig design

Application packages do not contain user photographs, research results, labels,
workspaces, private model authorization records, or pretrained model weights.
The public model manifest and fixed filter coefficients are included.

## Authors and license

Jianghua Zhang (张江华), Xinyu Wang (王欣宇), Wenhao Zhou (周文浩),
and Zhanyi Zhu (朱展翼).

WeCFU's original work is licensed under **CC BY-NC-SA 4.0**; see [LICENSE](LICENSE)
and [NOTICE](NOTICE). Commercial use requires separate permission from the
copyright holders. Third-party components retain their own licenses; see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Citation information will be
added when the accompanying publication is available.
