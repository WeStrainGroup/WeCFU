# Third-party notices

WeCFU's original application code is licensed under CC BY-NC-SA 4.0, as
described in LICENSE and NOTICE. Third-party components retain their own
licenses; the application's license does not replace their terms.

## SAM 2.1

Copyright (c) Meta Platforms, Inc. and affiliates. All rights reserved.

The setup command downloads the official SAM 2 source at commit
`2b90b9f5ceec907a1c18123530e92e794ad901a4` and the official SAM 2.1 Hiera Tiny
checkpoint. The upstream source and checkpoint are licensed under Apache
2.0. The complete license is included in [LICENSES/Apache-2.0.txt](LICENSES/Apache-2.0.txt)
and is retained with the downloaded source. See the
[fixed upstream repository](https://github.com/facebookresearch/sam2/tree/2b90b9f5ceec907a1c18123530e92e794ad901a4).

The source is downloaded without modifying its files. WeCFU supplies its own
image-processing recipe and runtime adapter. The optional connected-component
CUDA extension is not built by the supported CPU deployment. SAM's upstream
third-party notice for that extension is nevertheless preserved in
[LICENSES/SAM2-cctorch-BSD-3-Clause.txt](LICENSES/SAM2-cctorch-BSD-3-Clause.txt):
Copyright (c) 2020, the respective contributors, as shown by the AUTHORS file.

## ColonyGroundedSAM2 checkpoint

The colony Grounding DINO checkpoint is obtained from
[DataScienceWFSR/ColonyGroundedSAM2](https://huggingface.co/DataScienceWFSR/ColonyGroundedSAM2/tree/15b36f32ba3ba39ebd368bb98688bfa46144ac80),
revision `15b36f32ba3ba39ebd368bb98688bfa46144ac80`. The publisher's model-card
metadata declares Apache-2.0. The complete license text is included above.
WeCFU verifies the published checkpoint's fixed content identity and loads it
through its own adapter and the Transformers Grounding DINO implementation.
The author's separate application wrapper and training images are not bundled.

## Transformers and BERT tokenizer

[Hugging Face Transformers](https://github.com/huggingface/transformers/tree/v4.57.6)
4.57.6 is licensed under Apache-2.0. WeCFU's Grounding DINO key conversion,
configuration and loading adapter use its official architecture and conversion
conventions; WeCFU adds fixed-checkpoint validation and local execution controls.
Upstream Transformers copyright notices and license remain in the installed
dependency distribution.

The [Google BERT uncased tokenizer](https://huggingface.co/google-bert/bert-base-uncased/tree/86b5e0934494bd15c9632b12f734a8a67f723594)
uses revision `86b5e0934494bd15c9632b12f734a8a67f723594`, whose model card declares
Apache-2.0. Only the tokenizer and configuration files are downloaded; no
separate BERT checkpoint or example photographs are downloaded. Its model card
is retained in the model cache.

## Dependency distributions and model assets

The Python and Conda packages carry the application, public model configuration,
and these notices. Model weights and SAM source are obtained separately by the
explicit setup command; the Hugging Face container runs that command at build
time. All download URLs, fixed revisions, expected sizes and SHA-256 checksums
are in `wecfu/model_assets.json`.

PyTorch, torchvision, NumPy, SciPy, OpenCV, Pillow, scikit-image, pandas,
FastAPI, Pydantic, Uvicorn and the remaining runtime dependencies are separate
distributions with their own notices. Those notices are retained by the package
manager and in the container's installed distributions. No CFUCounter model
checkpoint or its application wrapper is distributed or used by this release.
