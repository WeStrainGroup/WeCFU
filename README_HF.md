---
title: WeCFU
emoji: 🦠
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
pinned: false
license: cc-by-nc-sa-4.0
short_description: Review colony counts with Fusion v2 and manual correction
---

# WeCFU 1.2.0

Import plate photos, request Fusion v2 candidates, review each marker, and export
CSV or a bundle with annotated images. The light interface also provides manual
marking and explicitly selected custom classical methods.

Fusion v2 combines SAM 2.1 with a colony Grounding DINO detector and a fixed
candidate filter. Its pinned CPU dependencies and verified model cache are
prepared when this Space builds. Missing models or inference errors are reported;
the app does not silently replace a model result with a classical count.

Declare front/empty plate views before using Fusion v2. Reverse views are not
supported by that recipe. Model candidates require human review; this release
does not establish accuracy across all organisms or imaging conditions.

Each visitor has a separate temporary workspace, limited to 100 images / 400 MB.
Uploaded photographs are processed on this server, without sending them to an
external inference API. **Export before leaving:** inactive workspaces are
removed after approximately one hour, and a Space restart can remove them sooner.

For persistent offline work, see the
[installation guide](https://github.com/WeStrainGroup/WeCFU/blob/main/INSTALL.md).
Source and notices: [WeStrainGroup/WeCFU](https://github.com/WeStrainGroup/WeCFU).

Authors: Jianghua Zhang, Xinyu Wang, Wenhao Zhou, Zhanyi Zhu.
Original application: CC BY-NC-SA 4.0. Third-party components retain their own
licenses; see THIRD_PARTY_NOTICES.md.
