# WeCFU 1.2.1

A browser workspace for counting colonies on petri-dish photographs, correcting
individual markers, and exporting counts with annotated images.

## Recognition modes

| Mode | Local application |
| --- | --- |
| **Ultra** | The default: a fixed image-processing + SAM 2.1 recipe. |
| **Lite** | The improved traditional algorithm, without loading a model. Faster and less demanding; complex colonies can require more manual correction. |
| **Custom** | Traditional recognition with adjustable color, brightness, shape and separation settings. These controls do not tune SAM. |

Manual marking remains available. If Ultra is unavailable or fails, WeCFU reports
the problem; it does not silently switch to Lite. You can choose Lite explicitly.
Changing modes does not change an already saved result.

## Install locally

The Conda package includes the application and traditional methods. Ultra also
requires the optional model dependencies and verified model cache on macOS or
Linux. Use Python 3.12 for the model runtime.

```sh
conda create -n wecfu -c westraingroup -c conda-forge python=3.12 pip wecfu=1.2.1 -y
conda activate wecfu
python -m pip install "wecfu[models] @ https://github.com/WeStrainGroup/WeCFU/releases/download/v1.2.1/wecfu-1.2.1-py3-none-any.whl"
python -m wecfu.setup_models
wecfu serve
```

On Linux, install the CPU-only PyTorch wheels in [INSTALL.md](INSTALL.md) before
the model extra. SAM workers stay loaded between requests by default, reducing
repeated startup work; predictions are never reused. Set
`WECFU_SAM_WARM_WORKER=0` before starting the server to use the cold-process route.

Windows supports Lite, Custom and manual marking. The model runtime supports
Linux CPU and macOS CPU/MPS; CUDA is not a supported device setting. See
[INSTALL.md](INSTALL.md) for core-only installation, cache setup and upgrades.

## Review and export

1. Add photos or drag in a folder. Importing or opening a photo does not run
   recognition. No front/blank/back selection is required.
2. Choose **Recognize all** to process unrecognized photos in Ultra or Lite.
   Existing results, including zero counts, and manual work are preserved.
   Processing is serial; you can stop after the current photo.
3. Use **Recognize current** to redo one photo. Ultra shows a preview before
   replacing an existing result; **Adopt result** saves it and can be undone.
   Lite directly recounts; replacing protected manual work requires confirmation.
4. In **Custom**, adjust the controls, choose **Apply**, then recognize the
   current photo or all photos. Apply only commits the settings. Custom batch
   recognition can replace machine results, but skips manual edits, notes,
   manually adjusted boundaries, manual mode and human verification records.
5. Correct missing or incorrect markers, add notes, then export CSV or a ZIP
   containing the CSV, annotated images and per-image JSON.

The list's hollow, light-gray and dark-gray dots mean unrecognized, machine
recognized, and viewed/edited. Viewing a photo is not accuracy verification.
Both marker types use solid lines: muted rose for machine marks and muted blue
for manual marks. Left click adds, right click removes, and Cmd/Ctrl-Z undoes an
edit. Left/right arrows navigate when an input control is not focused.

**Batch delete** removes selected photos and counting results from the workspace
after confirmation. Original files are unchanged; removal cannot be undone.
Local workspaces persist across restarts. See [USAGE.md](USAGE.md) for controls
and export fields.

Output still needs review. This release does not establish accuracy across all
organisms, media or imaging conditions. Marker circles identify locations; they
are not exact colony outlines.

## Use online

Open [WeCFU on Hugging Face](https://huggingface.co/spaces/WeCFU/wecfu).
The hosted app defaults to its classical Lite workflow and offers Custom
controls. When SAM is available, **Detailed check** previews a SAM result for
the current photo; it is not automatic or batch model recognition. The web
classical baseline can produce different results from local Lite or Ultra.

Each visitor has a separate temporary workspace, limited to 100 images. An
upload request is limited to 400 MiB. **Export before leaving:** inactive
workspaces are removed after approximately one hour, and a Space restart can
remove them sooner.

Hosted uploads are processed on that server, without sending them to an external
inference API. Local installation keeps photographs and processing on your
computer.

## Command line

```sh
wecfu batch /path/to/plate/photos --out /path/to/results
```

The batch command uses the classical command-line pipeline. It does not invoke
Ultra or SAM, and is separate from the browser's improved Lite workflow.

## Development and releases

- [Installation and operation](INSTALL.md)
- [User guide](USAGE.md)
- [Release and deployment procedure](SHARE.md)
- [Changes](CHANGELOG.md)
- [Imaging hardware](hardware/): the previously published camera/jig design

Packages do not contain user photographs, research labels/results, workspaces or
pretrained weights. Model identities and third-party notices are included.
Legacy Fusion resources remain for compatibility and provenance; they are not
the current recognition route.

## Authors and license

Jianghua Zhang (张江华), Xinyu Wang (王欣宇), Wenhao Zhou (周文浩),
and Zhanyi Zhu (朱展翼).

WeCFU's original work is licensed under **CC BY-NC-SA 4.0**; see [LICENSE](LICENSE)
and [NOTICE](NOTICE). Commercial use requires separate permission from the
copyright holders. Third-party components retain their own licenses; see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Citation information will be
added when the accompanying publication is available.
