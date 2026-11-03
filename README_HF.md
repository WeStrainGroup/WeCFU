---
title: WeCFU
emoji: 🦠
colorFrom: gray
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
license: cc-by-nc-sa-4.0
short_description: Count colonies, correct markers, export results
---

# WeCFU 1.2.1

Add plate photos, choose **Recognize all**, correct individual markers, and
export counts as CSV or a bundle of annotated results.

This hosted version defaults to the **classical image-processing workflow**,
with Lite and Custom controls. **Detailed check** can explicitly preview a SAM
result for the current photo when the runtime is available. It does not run
models automatically or in a batch. Local WeCFU also offers Ultra (algorithm +
SAM) and an improved Lite algorithm; results can differ from this web baseline.

Importing a photo does not start recognition. Lite's **Recognize all** preserves
existing results and manual work. In Custom, adjust parameters, choose
**Apply**, then recognize the current photo or all photos. Custom batch
recognition can replace machine-only results, but skips manual edits, notes
and other protected work.

Machine markers are muted rose, and manual markers muted blue. Add a marker
with a left click; remove one with a right click. Review missed, false and
merged colonies before exporting. Opening a photo records it as viewed, not
as an accuracy-verified reference. Marker circles are location aids, not exact
colony outlines.

Each visitor has a separate temporary workspace, limited to **100 images** and
**400 MiB per upload request**. Uploaded photographs are processed on this
server, without forwarding them to an external inference API. **Export before
leaving:** inactive workspaces are removed after approximately one hour, and a
Space restart can remove them sooner. The ZIP export contains counts,
annotated images and JSON, not the original input photos.

For persistent local work and optional SAM support, see the
[installation guide](https://github.com/WeStrainGroup/WeCFU/blob/main/INSTALL.md).
Source, user guide and notices:
[WeStrainGroup/WeCFU](https://github.com/WeStrainGroup/WeCFU).

No broad accuracy claim is made for all organisms, media or imaging conditions.

Authors: Jianghua Zhang, Xinyu Wang, Wenhao Zhou, Zhanyi Zhu.
Original application: CC BY-NC-SA 4.0. Third-party components retain their own
licenses; see THIRD_PARTY_NOTICES.md.
