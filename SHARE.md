# Publish a reviewed WeCFU 1.2.1 release

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

For 1.2.1, the local default is **Ultra: fixed algorithm + SAM**. Lite preserves
the improved classical method; Custom applies user-selected classical settings.
New requests do not use the legacy Fusion route. Existing Fusion results and
provenance remain readable; do not relabel them as current Ultra results.

Hosted mode defaults to its classical baseline. It may offer an explicit,
current-photo SAM preview when available; it does not run model batch recognition.
Do not advertise local and hosted default recognition as identical.

1. Set the same version in `wecfu/__init__.py`, `pyproject.toml` and `meta.yaml`.
   Update CHANGELOG, installation examples and model notices where applicable.
2. Review every staged path and public JSON resource. MANIFEST.in and
   pyproject.toml define the package allowlist. Photographs, model weights,
   source-view registries, private authorization records and research results
   must stay outside the release and Docker context.
3. Run the maintained Python and Node checks. In disposable synthetic
   workspaces, verify imports, current/all recognition routing, manual-work
   protection, source/revision conflicts, batch deletion, save/undo, export,
   all five Help languages and hosted session isolation. Validate configured
   model availability separately from a pure-classical request. Do not use an
   active user's workspace for release acceptance.
4. Verify warm-worker lifecycle and explicit cold rollback. Warm workers are
   enabled by default in 1.2.1; `WECFU_SAM_WARM_WORKER=0` retains the cold route.
   Do not change weights, numerical settings or thresholds as part of packaging.
5. Commit the final reviewed product files before building. The Conda recipe
   snapshots Git HEAD; uncommitted changes are not included.

The model runtime uses Python 3.12 and the `models` extra's pinned dependencies.
`wecfu/model_assets.json` fixes public source revisions, URLs, sizes and hashes.
Setup downloads that shared asset manifest, including retained legacy assets;
counting requests only read the verified cache. The Docker image installs the
CPU runtime and prepares its cache to support explicit hosted SAM previews.

## Build and inspect artifacts

From the reviewed release commit:

```sh
python -m build
conda build . -c conda-forge --no-anaconda-upload
python tests/test_release_packaging.py dist/wecfu-1.2.1-py3-none-any.whl dist/wecfu-1.2.1.tar.gz
```

Pass the actual `.conda` path printed by conda-build to the same auditor:

```sh
python tests/test_release_packaging.py /path/to/wecfu-1.2.1-py_0.conda
```

The auditor reads archive members without installation or extraction. It checks
for required runtime code/resources and rejects unapproved data. Its `.conda`
reader requires `zstandard`. Install the built artifacts in clean environments
and run CLI/API smoke checks; a source-tree pass alone does not validate the
package contents. Confirm Ultra/Lite/Custom configuration, required warm-worker
files, translated Help and the explicit unavailable-model behavior in the
installed artifact. A core-only Conda install must still offer Lite/Custom.

## Publish GitHub and Conda

After artifact inspection and clean-install validation:

```sh
git tag v1.2.1
git push github HEAD:main v1.2.1
gh release create v1.2.1 --repo WeStrainGroup/WeCFU --verify-tag \
  dist/wecfu-1.2.1-py3-none-any.whl dist/wecfu-1.2.1.tar.gz \
  --title 'WeCFU 1.2.1' --notes-file CHANGELOG.md
anaconda --at anaconda.org whoami
anaconda --at anaconda.org upload /path/to/wecfu-1.2.1-py_0.conda
```

Use the actual reviewed ref if it differs from `main`. Reuse existing
credentials; do not put tokens or passwords in repository files or output.
Verify the public asset list and Conda channel version after upload. Do not
replace an existing published version's artifacts with different bytes; use a
new release version when a published package needs correction.

The noarch Conda package omits large model dependencies and weights. Publish
the matching GitHub wheel first so INSTALL.md's optional-model command works
when the Conda release becomes visible. Do not describe a core-only install as
having a ready SAM runtime. Existing users should export, stop the server,
upgrade, restart with their existing workspace and reload the browser page.
An upgrade does not automatically recount stored results.

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
default Lite/baseline route, available explicit SAM preview, multilingual Help,
synthetic upload/count/apply/export and two isolated visitor sessions. A
successful push is not a successful deployment. Record the source commit,
artifact hashes and Space commit together; report any failed channel explicitly.
Do not infer model readiness from an ordinary page load.

Hosted workspaces are temporary. Redeployment can discard active sessions;
user uploads and exported files are not part of a release.
