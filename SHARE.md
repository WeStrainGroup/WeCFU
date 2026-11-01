# Publish a reviewed WeCFU release

The existing public targets are:

| Channel | Target |
| --- | --- |
| GitHub source and release files | https://github.com/WeStrainGroup/WeCFU |
| Conda package | https://anaconda.org/westraingroup/wecfu |
| Hosted Docker application | https://huggingface.co/spaces/WeCFU/wecfu |

Use a clean, reviewed release checkout. Keep private development history,
workspaces, research notes and model caches outside it. The GitHub repository's
previously published hardware files are not part of the Python/Conda artifacts
or the hosted application. Do not copy them into the Hugging Face checkout.

## Prepare one consistent release

1. Set the same version in `wecfu/__init__.py`, `pyproject.toml` and `meta.yaml`.
   Update CHANGELOG, installation examples and the model notices when applicable.
2. Review every staged path and the public JSON resources. The package allowlist
   is in MANIFEST.in and pyproject.toml. No photographs, model weight binaries,
   source-view registries, private authorization records or research results
   belong in the commit or build context.
3. Run the maintained Python and Node tests. Exercise editing/export and model
   candidate application in a disposable synthetic workspace. Check local and
   hosted session isolation. Use the selected fixed model runtime and cache;
   do not reuse a user's working directory for acceptance tests.
4. Commit the final product files before building. The Conda recipe snapshots
   Git HEAD; uncommitted edits will not be included.

The model runtime uses Python 3.12. Its dependency pins are in the `models` extra.
`wecfu/model_assets.json` fixes public source revisions, URLs, sizes and hashes.
The setup command downloads those assets; model requests only read the verified
local cache. Docker installs the official CPU PyTorch wheels and prepares that
cache before starting the web application.

## Build and inspect artifacts

From the reviewed release commit:

```sh
python -m build
conda build . -c conda-forge --no-anaconda-upload
python tests/test_release_packaging.py dist/wecfu-1.2.0-py3-none-any.whl dist/wecfu-1.2.0.tar.gz
```

Pass the actual `.conda` output path printed by conda-build to the same auditor:

```sh
python tests/test_release_packaging.py /path/to/wecfu-1.2.0-py_0.conda
```

The auditor reads archive members without installing or extracting them. It
rejects unapproved resources and checks that all public runtime JSON, setup
code, interface files and third-party notices are present. The `.conda` reader
requires `zstandard`, supplied by the build environment. Also install the built
core package and wheel in clean environments and run their CLI/API smoke tests.
A source-tree test pass does not prove that the distribution contains its assets.

## Publish GitHub and Conda

After artifact inspection and clean-install validation:

```sh
git tag v1.2.0
git push github HEAD:main v1.2.0
gh release create v1.2.0 --repo WeStrainGroup/WeCFU --verify-tag \
  dist/wecfu-1.2.0-py3-none-any.whl dist/wecfu-1.2.0.tar.gz \
  --title 'WeCFU 1.2.0' --notes-file CHANGELOG.md
anaconda --at anaconda.org whoami
anaconda --at anaconda.org upload /path/to/wecfu-1.2.0-py_0.conda
```

Use the actual reviewed branch/ref if it differs from `main`; do not publish a
stale branch merely because an example names it. Existing authentication can be
reused. Never place tokens or passwords in repository files or command output.
After upload, verify the public release asset list and the Conda channel version.

The noarch Conda package deliberately omits large model dependencies and weights.
Publish the matching GitHub wheel first so INSTALL.md's model-extra command is
usable as soon as the Conda version appears. Do not advertise the core-only
package as having a ready-to-run Fusion model cache.

## Update the existing Hugging Face Space

Use a separate checkout of the existing Space `main`, preserving its history.
Copy only the reviewed public application files, `pyproject.toml`, Dockerfile,
`.dockerignore`, LICENSE, NOTICE, THIRD_PARTY_NOTICES.md and LICENSES. Use
`README_HF.md` as that checkout's `README.md`. Keep ordinary GitHub documentation
separate. Review deletions as well as additions so removed code is not left behind.

Commit the reviewed diff and push normally to the existing Space `main`. Do not
merge the application's entire Git history, reset a shared working checkout or
force-push the Space. The Docker build installs the model extra, downloads its
fixed assets and runs an asset check; a failure must leave deployment incomplete
rather than removing model functionality.

Wait for the actual build and runtime status. Then verify the displayed version,
Fusion v2 availability, a synthetic inference request, candidate application,
export and two separate visitor sessions. A successful Git push alone is not a
successful deployment. Record the published source commit, artifact hashes and
Space commit together; report any failed channel explicitly.

Hosted workspaces remain ephemeral. Exported user files and sessions are not
part of a release, and redeployment can discard active hosted sessions.
