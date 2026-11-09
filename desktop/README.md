# WeCFU Desktop

Desktop candidate **1.3.0-rc.1**. This directory is not a declaration of public
release readiness. The existing Conda/web application version remains 1.2.3.

## User experience

- Open WeCFU as a desktop application; Conda, Python and a terminal are not needed.
- Import plate photographs, select **Ultra**, **Lite**, or **Custom**, and recognize
  the current image or the whole batch.
- Ultra uses the existing algorithm and the fixed SAM recipe. Lite uses the
  existing algorithm alone. This desktop work does not train a model or change
  the numerical recipe.
- Review or edit the rings and export CSV or the image/results archive. Exports
  are saved to Downloads, with a new filename if the chosen name already exists.
- Each launch starts an empty temporary workspace. Export before closing. The
  original imported photographs are not edited or deleted.
- The complete inference environment is bundled. Recognition runs locally and
  does not upload photographs. The GitHub link opens the system browser only
  when selected.

## Initial target platforms

| Target | Runtime | Acceptance required before release |
| --- | --- | --- |
| Apple Silicon Mac, macOS 14+ | CPU or MPS selected by the existing capability probe | Installed app, actual WebView import/current/batch/edit/export/restart |
| Windows 11 x64 | CPU | Windows native process/pipe tests, complete bundled inference, installed NSIS app, WebView import/current/batch/edit/export/restart |

Intel Mac, Windows ARM and CUDA are not included in this first desktop package.
Passing Mac checks is not evidence of Windows compatibility. Windows CI backend
acceptance and interactive Windows application acceptance are distinct records.

## Architecture

Tauri 2 displays the existing interface. A real relocatable CPython 3.12 runtime
runs FastAPI and SAM as owned local processes. Python is not a frozen launcher
mistaken for an interpreter. All model code, weights and dependencies are
packaged from fixed sources; the application does not install packages at launch.

The shell verifies the complete resource inventory and SHA256 digests before
launching the backend. The backend binds to an available loopback port and emits
a bounded readiness message. A per-launch HttpOnly cookie and Host/Origin checks
protect the local API. The launch capability is removed from page history.
There are no frontend filesystem or shell permissions.

The native process owns the backend lifetime. Windows uses a Job Object assigned
before the backend executes; the Python worker layer also owns its children.
Mac uses a separate process group. Closing the window asks the backend to stop,
then retires that invocation's remaining processes. It never searches for and
kills unrelated Python processes or an existing WeCFU service.

## Build

Use the native target OS. Build requirements are Python 3.12, Node, Rust and the
native Tauri prerequisites. These are developer tools, not end-user requirements.

```sh
python tools/build_desktop_resources.py --output desktop/bundle --version 1.3.0-rc.1
cd desktop
npm ci
npm run build -- --bundles app --config src-tauri/tauri.macos.conf.json
# Windows: npm run build -- --bundles nsis --config src-tauri/tauri.windows.conf.json
```

The resource builder downloads the pinned official python-build-standalone
archive, verifies its SHA256, installs the fixed model requirements, and copies
verified SAM resources. It includes dependency metadata and license notices.
`--model-cache` can use an existing verified model cache for an offline build;
`--archive` can use a previously verified Python archive. Neither option changes
the fixed source/weight hashes.

After a source-only change, `--refresh-app` validates the previous bundle and
preserves its verified runtime and model resources. It refuses unowned/nonempty
outputs, unexplained files and changed preserved resources. Bundle resources,
compiled binaries, photos and test outputs are not committed to source control.

### macOS candidate packaging

Build the `.app` first. A linker-signed executable alone is not a complete signed
app bundle; do not distribute a DMG if `codesign --verify --deep --strict` fails.
For a local candidate without a Developer ID identity, use this order:

1. Copy the built `.app` with `ditto` into a new staging directory. Preserve the
   original build and previous candidates. Record the resource manifest SHA256.
2. Ad-hoc sign **only the outer app**, then verify the complete bundle:

   ```sh
   codesign --force --sign - "$WECFU_STAGING/WeCFU.app"
   codesign --verify --deep --strict --verbose=2 "$WECFU_STAGING/WeCFU.app"
   codesign -dv --verbose=4 "$WECFU_STAGING/WeCFU.app"
   ```

   `WECFU_STAGING` is the new staging directory. Do not add `--deep` to the
   signing command: recursively re-signing the bundled runtime can change files
   covered by `Contents/Resources/bundle/bundle-manifest.json`. If verification
   fails for an internal binary, investigate it before changing that payload.
3. Verify that the manifest SHA256 is unchanged, every file digest still matches
   `files`, and the resource inventory has no missing or extra files. Signing may
   change the outer executable and add `Contents/_CodeSignature`; it must not
   change the runtime, model, or application resources covered by the manifest.
4. Add an `Applications` symlink to `/Applications` beside the staged app. Create
   a new UDZO image and validate it; use a new filename rather than overwriting
   prior evidence:

   ```sh
   ln -s /Applications "$WECFU_STAGING/Applications"
   hdiutil create -srcfolder "$WECFU_STAGING" -volname WeCFU \
     -format UDZO -fs HFS+ -noatomic -nospotlight "$WECFU_DMG"
   hdiutil verify "$WECFU_DMG"
   ```

5. Mount that image read-only, copy the app into a fresh installation directory,
   and repeat the complete resource and strict signature checks on the copy.
   Record its manifest, native executable and DMG hashes. Unmount only the image
   created for this check. Perform native-window acceptance on this installed
   copy, including exports and cleanup on close.

An ad-hoc signed candidate has no Developer ID identity or notarization. Passing
these checks establishes package integrity, not Gatekeeper approval for public
distribution. Keep the signature and installation results with the candidate.

Windows candidates use NSIS zlib compression to keep rebuilds practical. This
changes installer compression only; the installed resource inventory and file
hashes must still match the complete bundle.

## Acceptance and release

`tools/desktop_acceptance.py` performs bounded, actual bundled inference on two
synthetic images, validates current/batch recognition, manual edits, CSV/ZIP
exports, shutdown and a new empty session. It is API acceptance, not a substitute
for using the native window. It does not measure scientific accuracy.

```sh
python tools/desktop_acceptance.py --bundle desktop/bundle --output acceptance-new
```

The Windows workflow builds and tests a candidate artifact without publishing a
release. Keep failed logs and corrections. A release must be built from the
reviewed commit, tested after packaging, and accompanied by hashes and a clear
platform acceptance record.

Public macOS distribution additionally needs Developer ID signing and Apple
notarization. Public Windows distribution needs an appropriate code-signing
identity and installation verification. An unsigned candidate must be labeled
as such; compiling it does not establish trusted installation on another computer.
