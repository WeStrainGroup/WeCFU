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

# WeCFU 1.2.5

Add plate photos, choose **Recognize all**, correct individual markers, and
export counts as CSV or a bundle of annotated results.

Choose one of three modes:

- **Ultra** (default): improved image processing with SAM.
- **Lite**: the improved algorithm, with lower resource use.
- **Custom**: adjustable algorithm parameters.

Importing a photo does not start recognition. **Recognize all** processes
unrecognized photos in order and preserves existing results and manual work.
**Recognize current** processes one photo. Ultra previews a replacement for an
existing result; adopt it or cancel. New Ultra results save directly. In
Custom, adjust parameters, choose **Apply**, then recognize the current photo
or all photos. Custom batch recognition can replace machine-only results, but
skips manual edits, notes and other protected work.

The interface starts in English and remembers your choice of English,
Simplified Chinese, French or Russian.

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

For local processing, automatic SAM setup and optional persistent workspaces, see the
[installation guide](https://github.com/WeStrainGroup/WeCFU/blob/main/INSTALL.md).
Source, user guide and notices:
[WeStrainGroup/WeCFU](https://github.com/WeStrainGroup/WeCFU).

No broad accuracy claim is made for all organisms, media or imaging conditions.

Authors: Jianghua Zhang, Xinyu Wang, Wenhao Zhou, Zhanyi Zhu.
Original application: CC BY-NC-SA 4.0. Third-party components retain their own
licenses; see THIRD_PARTY_NOTICES.md.
