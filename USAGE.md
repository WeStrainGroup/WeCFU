# Using WeCFU 1.2.1

For installation and model setup, see [INSTALL.md](INSTALL.md).

## Add and recognize photos

Use **Add images**, or drop JPG, JPEG, PNG, TIF or TIFF files/folders into the
page. The local app also accepts an image or folder path. Importing only adds
photos; opening one does not run recognition. Original files are not modified.

The local app offers three modes:

- **Ultra**: fixed image-processing + SAM recognition, without DINO.
- **Lite**: the improved traditional algorithm, with lower resource use.
- **Custom**: traditional recognition with adjustable parameters; sliders do
  not tune SAM.

The hosted app defaults to the classical Lite workflow and offers Custom
controls. Detailed check can explicitly preview SAM for the current photo
when available. Its classical baseline can differ from local Lite. If local
Ultra cannot run, it reports the problem; select Lite explicitly for the
non-model route.

**Recognize all** in Ultra or Lite processes unrecognized photos one at a time.
Already recognized photos, including zero-count results, are skipped. Existing
manual work, notes and verification records are preserved. Keep the page open;
**Stop after this image** finishes the current request before stopping. Expand
the batch report to inspect completed, skipped and failed photos.

**Recognize current** handles only the selected photo. Ultra saves a new,
untouched photo's result directly. For an existing result, it displays a SAM
preview: **Adopt result** replaces the saved markers; **Cancel preview** keeps
them. During preview, the image shows the candidate alone and labels its count;
the saved result remains unchanged. Adoption can be undone. In Lite, the
current photo is recounted directly, with confirmation before replacing
protected manual work. **Detailed check** in Lite offers a SAM preview when
the model is available; cancelling returns to Lite.

## Custom adjustments

Choose Custom, adjust the sliders or click their numeric values to type a value,
then choose **Apply**. Apply commits the working settings and closes the panel;
it does not recognize a photo. Choose **Recognize current** or **Recognize all**
afterwards. **Adjust** reopens the panel. Unapplied changes do not affect a run.
The applied settings carry across photos in the current page.

The bright mint preview shows pixels selected by the foreground threshold,
not final colonies. Shape filtering, small-colony filtering and splitting are
evaluated during recognition.

Custom **Recognize all** can replace existing machine-only results. It skips
manual edits, notes, manually adjusted boundaries, pure manual mode and human
verification records. Merely viewing a photo is not such protection. For a
protected current photo, recounting requires confirmation and can be undone.

## Correct marks and navigate

- Left click adds a marker; right click removes one. A quick drag selects
  multiple markers for removal. Hold before dragging to pan; scroll to zoom.
- Click outside the photo, use the fit-view control, or press **F** to fit the
  full photo. **← / →** switch photos. Input fields, sliders and selectors keep
  their own arrow-key behavior while focused.
- **Cmd/Ctrl-Z** or **Undo** restores an earlier edit in the current page.
- **Manual marks** changes the size of future manual markers, not existing
  markers or recognition parameters.
- **More** contains pure manual mode, boundary adjustment, clear marks and
  remove photo. The medium boundary limits machine recognition without
  cropping the displayed image; changing it does not automatically recount.

Machine markers are muted rose and manual markers muted blue, both solid.
Their circles indicate locations rather than exact colony outlines. Review
misses, false marks and touching colonies before using the counts.

## Status, saving and deletion

The photo-list dots mean: hollow = not recognized; light gray = machine
recognized; dark gray = viewed or edited. Opening a photo records its viewing
status. **Viewing is not accuracy verification.** Explicit reference confirmation
is a separate feature in internal review queues.

Edits and notes save to the workspace; watch the save indicator and retry if it
reports failure. Local workspaces persist across server restarts. Undo history
is a current-page convenience, not a backup of every prior session.

Use **Batch delete**, select photos or **Select all**, then **Delete selected**.
Check the confirmation before proceeding. This removes workspace entries and
their counting results; original source photos are unchanged. Deletion cannot
be undone. A failure is reported separately from successful removals.

## Export

**Export CSV** saves one row per photo with filename, final count, initial
machine count, removed-machine-marker count, manual additions and notes.
Photos without saved state have empty count fields. An opened but unrecognized
photo can have an empty saved marker set exported as zero: finish recognition
or manual counting before treating an exported zero as a verified zero.

**Export bundle** adds annotated images and per-image JSON to the CSV in a ZIP.
It does not include the original input photos. Preparing annotated images can
take longer than CSV alone. The browser downloads the file; supported local
browsers can also choose a destination folder.

Hosted uploads are processed on the server in a temporary visitor workspace:
up to 100 images, and 400 MiB per upload request. Inactive workspaces are cleaned
after approximately one hour; server restarts can remove them sooner. Export
before leaving. The local app keeps processing and workspace files on your
computer and does not have these hosted-session limits.
