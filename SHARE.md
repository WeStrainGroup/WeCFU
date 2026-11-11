# Publish a reviewed WeCFU 1.2.4 release

The existing public targets are:

| Channel | Target |
| --- | --- |
| GitHub source and release files | https://github.com/WeStrainGroup/WeCFU |
| Conda package | https://anaconda.org/westraingroup/wecfu |
| Hosted Docker application | https://huggingface.co/spaces/WeCFU/wecfu |

Use a clean, reviewed release checkout. Keep private development history,
workspaces, research notes and model caches outside it. Previously published
hardware files belong to GitHub only, not the Python/Conda artifacts or the
Hugging Face application checkout.

## Keep the release contract consistent

For 1.2.4, the local default is **Ultra: fixed algorithm + SAM**. Lite preserves
the improved classical method; Custom applies user-selected classical settings.
New requests do not use the legacy Fusion route. Existing Fusion results and
provenance remain readable; do not relabel them as current Ultra results.

Hosted and local mode selection is Ultra, Lite and Custom, with Ultra selected
by default. Ultra supports current-photo recognition and serial batches.
The separate Detailed check action has been removed. Unsupported local systems
must report Ultra unavailable rather than silently substitute Lite.

1. Set the same version in `wecfu/__init__.py`, `pyproject.toml` and `meta.yaml`.
   Update CHANGELOG, installation examples and model notices where applicable.
2. Review every staged path and public JSON resource. MANIFEST.in and
   pyproject.toml define the package allowlist. Photographs, model weights,
   source-view registries, private authorization records and research results
   must stay outside the release and Docker context.
3. Run the maintained Python and Node checks. In disposable synthetic
   workspaces, verify imports, current/all recognition routing, manual-work
   protection, source/revision conflicts, batch deletion, save/undo, export,
   all four Help languages (en, zh-CN, fr, ru) and hosted session isolation. Validate configured
   model availability separately from a pure-classical request. Do not use an
   active user's workspace for release acceptance. Check that the first locale
   is English, a saved supported choice is retained, and old ja/es preferences
   fall back to English. Check fresh default sessions, cleanup on server stop,
   and preservation of explicitly chosen `--root` workspaces.
4. Verify warm-worker lifecycle and explicit cold rollback. Warm workers are
   enabled by default in 1.2.4; `WECFU_SAM_WARM_WORKER=0` retains the cold route.
   Do not change weights, numerical settings or thresholds as part of packaging.
5. Commit the final reviewed product files before building. The Conda recipe
   snapshots Git HEAD; uncommitted changes are not included.

The model runtime uses Python 3.12 and pinned dependencies. A normal local
`wecfu serve` prepares a separate runtime environment in the model cache,
downloads only the fixed official SAM source and checkpoint, verifies them,
then opens the page. It reuses verified resources on later launches.
`--no-model-setup` skips this preparation for offline or managed use.
`wecfu/model_assets.json` fixes source revisions, URLs, sizes and hashes.
`setup_models` defaults to SAM; `--profile all` retains the old full-asset setup
for explicit legacy use. The Docker image prepares its CPU SAM runtime and
cache during the build. Neither package archives nor the Space repository
contain pretrained weights.

## Build and inspect artifacts

From the reviewed release commit:

```sh
python -m build
conda build . -c conda-forge --no-anaconda-upload
python tests/test_release_packaging.py dist/wecfu-1.2.4-py3-none-any.whl dist/wecfu-1.2.4.tar.gz
```

Pass the actual `.conda` path printed by conda-build to the same auditor:

```sh
python tests/test_release_packaging.py /path/to/wecfu-1.2.4-py_0.conda
```

The auditor reads archive members without installation or extraction. It checks
for required runtime code/resources and rejects unapproved data. Its `.conda`
reader requires `zstandard`. Install the built artifacts in clean environments
and run CLI/API smoke checks; a source-tree pass alone does not validate the
package contents. Confirm Ultra/Lite/Custom configuration, required warm-worker
files, translated Help and the explicit unavailable-model behavior in the
installed artifact. Validate first-launch preparation from the actual Conda
package and a clean cache on a supported platform, then confirm cache reuse.
Do not publish until an actual fresh Conda environment has completed automatic
setup and recognized a synthetic photo with Ultra, including a saved result.
Run the ordinary `wecfu serve` command with browser auto-open enabled, outside
the source checkout. Inspect the actual browser page immediately: current UI,
Ultra selected and no connection error, even when the same localhost origin
has a cached earlier version. Import multiple synthetic images through the UI,
recognize current/all, inspect the saved model provenance, and download exports.
API-only checks or manually opening a page after readiness do not satisfy this
user-flow gate. After publication, install from the public Conda channel and
repeat normal startup; match installed files to the reviewed artifact.

Then stop that server and start it again: the default workspace must be empty,
the model cache must be reused, and a separate explicit `--root` workspace must
remain intact. Mocked availability checks alone do not satisfy this gate.
With setup explicitly skipped, a core-only install must still offer Lite/Custom.
Windows x64 may offer Ultra only after the Windows CPU runtime and assets
have passed verification. Windows ARM must report it unavailable. Every
installation requires Python 3.12. Record Mac, Linux and Windows acceptance
separately; never treat a noarch package as evidence of cross-platform testing.

## Publish GitHub and Conda

After artifact inspection and clean-install validation:

```sh
git tag v1.2.4
git push github HEAD:main v1.2.4
gh release create v1.2.4 --repo WeStrainGroup/WeCFU --verify-tag \
  dist/wecfu-1.2.4-py3-none-any.whl dist/wecfu-1.2.4.tar.gz \
  --title 'WeCFU 1.2.4' --notes-file CHANGELOG.md
anaconda org whoami
anaconda org upload --user WeStrainGroup --label main /path/to/wecfu-1.2.4-py_0.conda
```

Use the actual reviewed ref if it differs from `main`. Reuse existing
credentials; do not put tokens or passwords in repository files or output.
Verify the public asset list and Conda channel version after upload. Do not
replace an existing published version's artifacts with different bytes; use a
new release version when a published package needs correction.

The noarch Conda package omits model dependencies and weights; normal startup
prepares them in the user cache. Do not call a runtime ready until its
verification passes. Existing users must export needed results, stop the old
server, upgrade, restart, then reload the browser. New default sessions are
empty. Old `./data` directories remain untouched; an explicit `--root` resumes
persistent work. An upgrade does not recount stored results.

## Update the existing Hugging Face Space

Use a separate checkout of the existing Space `main`, preserving its history.
Copy only reviewed public application files, `pyproject.toml`, Dockerfile,
`.dockerignore`, LICENSE, NOTICE, THIRD_PARTY_NOTICES.md and LICENSES. Use
`README_HF.md` as the Space's `README.md`. Review deletions too, so removed code
is not left behind. Do not copy private data, the application's full Git
history or the hardware directory into the Space.

Commit the reviewed diff and push normally to the existing Space `main`.
Do not reset a shared checkout or force-push. Model setup/build verification
must fail clearly if assets or dependencies are unavailable.

Wait for actual build and runtime completion. Check the displayed version,
default Ultra route, all three modes, current/batch SAM recognition,
multilingual Help, synthetic upload/count/apply/export and two isolated visitor
sessions. A successful push is not a successful deployment. Record the source commit,
artifact hashes and Space commit together; report any failed channel explicitly.
Do not infer model readiness from an ordinary page load.

Hosted workspaces are temporary. Redeployment can discard active sessions;
user uploads and exported files are not part of a release.
