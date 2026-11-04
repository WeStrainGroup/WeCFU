# Changelog

## 1.2.2

- Use the same Ultra, Lite and Custom mode selection locally and on the hosted
  app, with Ultra selected by default. Remove the separate Detailed check action.
- Prepare the fixed SAM runtime automatically on first local startup on macOS
  and Linux, using an isolated cached environment. Download only SAM assets by
  default; retain the full legacy asset profile as an explicit option.
- Require Python 3.12. Windows continues to support Lite, Custom and manual
  marking; Ultra remains unavailable there.
- Start a fresh local session by default and clean it up when the server stops.
  Browser refresh keeps the current session; an explicit `--root` retains a
  persistent workspace. Original photographs and older workspaces are untouched.
- Open in English initially and remember a supported language choice. Replace
  Japanese and Spanish with Russian; retain English, Chinese and French. Update
  Help for the current recognition, session and export workflows.

## 1.2.1

- Ultra is the local algorithm + SAM workflow; Lite keeps the improved classical algorithm.
- Recognize all processes photos sequentially with existing results and manual work protected.
- Reuse the SAM worker and distance transform to reduce repeated work without changing model settings.
- Apply custom settings once, close the panel, then recognize the current photo or the batch.
- Add batch deletion, consistent rose/blue markers, keyboard navigation fixes and synchronized photo status.
- Refresh help in English, Chinese, Japanese, Spanish and French, with concise mode explanations.


## 1.2.0

- Add the Fusion v2 automatic workflow using fixed SAM 2.1, colony Grounding DINO
  and candidate-filter components, with declared front/empty plate input views.
- Provide portable, explicitly installed model assets and pinned dependencies;
  verify asset content before use. The hosted Docker build prepares a CPU model
  cache. Model errors remain visible and never trigger a silent classical fallback.
- Refresh the interface with a light theme, default/custom method controls,
  clearer manual correction tools and a collapsible export area.
- Preserve local workspaces across application restarts. Separate hosted visitors'
  temporary workspaces and retain explicit candidate application, undo and saved
  model provenance.
- Improve editing, navigation, view controls and export handling. Export the
  saved count together with user corrections and per-image state.
- Keep public application packages free of user photographs, workspaces, research
  records, training labels and pretrained weight binaries. Include public model
  configuration and third-party notices.

These changes describe product functionality. They do not claim independent
accuracy validation or consistent improvements across species, media or cameras.

## 1.1.0

- Published the application under CC BY-NC-SA 4.0 with attribution in NOTICE.
