# ID Photo Auto Cropper

**Repository:** https://github.com/skyemain/cropper

## For Windows users (no Python required)

You only need **one file**:

| File | What it does |
|------|----------------|
| **`IDPhotoAutoCropper-Setup.exe`** | **Recommended.** Install like any normal app. Start Menu shortcut. Uninstall from Windows Settings → Apps. Run a newer Setup to upgrade in place. |
| **`IDPhotoAutoCropper.exe`** | Portable — copy this single file anywhere and double-click. To update, delete the old file and copy the new one. |

Download from **[GitHub Releases](https://github.com/skyemain/cropper/releases)** (or ask whoever built the app for these files).

**Unzipped the source zip?** There is no `.exe` inside it — read **[START_HERE.txt](START_HERE.txt)** or run **`Download the ready-made app.bat`**.

**Install:** double-click `IDPhotoAutoCropper-Setup.exe` → Next → Install → open from Start Menu.

**Update:** download the new `IDPhotoAutoCropper-Setup.exe` and run it — the old version is replaced automatically. Or uninstall from Settings → Apps first, then install.

**Uninstall:** Settings → Apps → ID Photo Auto Cropper → Uninstall.

Full step-by-step guide: [INSTALL.txt](INSTALL.txt)

You never need to run `.bat` files, Python, or pip unless you are developing the app yourself.

---

A Windows desktop application that turns folders of ordinary portrait
photographs (`IMG_0001.JPG`, `DSC_4382.JPG`, ...) into standardized ID-card
portraits: it detects the face, locates the eyes, levels the eye line, scales
the face to a consistent size, positions the eyes at a consistent point, and
crops to exact output dimensions - for hundreds or thousands of photos in one
batch.

Everything runs **locally and offline**. Photos never leave the computer, no
face recognition is performed, and facial landmarks are used only for
geometric alignment.

![Application](assets/icon.png)

## Source safety guarantee

The source folder is treated as strictly read-only:

* originals are never renamed, moved, overwritten, rotated, or deleted;
* results are written to a **sibling** folder named `<source>_crop`
  (e.g. `C:\Photos\Employee_IDs` -> `C:\Photos\Employee_IDs_crop`);
* output filenames are identical to the source filenames (numbering,
  leading zeros, and the file extension are preserved);
* every single write passes a centralized safety check
  (`utilities/paths.py: validate_output_path`) that rejects any destination
  that resolves outside the `_crop` folder or inside the source folder;
* an automated test hashes all source files before and after a batch and
  proves they are bit-for-bit unchanged (`tests/test_safety.py`).

## Output layout

```
C:\Photos\Employee_IDs_crop\
    IMG_0001.JPG                 <- processed portraits (SUCCESS)
    IMG_0002.JPG
    REVIEW\IMG_0004.JPG          <- processed, but flagged for human review
    FAILED\IMG_0099.JPG          <- unprocessable (copy of the original)
    CONTACT_SHEETS\contact_sheet_001.jpg
    processing_report.csv        <- one row per image with QA measurements
    processing.log               <- technical log for the batch
```

Classification:

* **SUCCESS** - one clear face, reliable landmarks, clean crop.
* **REVIEW** - processed, but a human should look: multiple faces, strong
  head rotation (yaw/pitch/roll), very small face, face touching the photo
  edge, low detection confidence, possible hair/chin cut-off, crop window
  leaving the photo, or blur below the threshold.
* **FAILED** - unreadable/corrupt image, no detectable face, or landmarks
  unavailable. A copy of the original is placed in `FAILED\` for inspection;
  the original itself is never touched.
* **SKIPPED** - output already exists (in "Continue / Skip Existing" mode).

## Features

* **Preview** - ORIGINAL | CROPPED side by side using the exact batch
  pipeline, with Previous / Next / Auto Process Preview / Reset and an
  optional detection overlay (face box, eye centers, eye line, landmarks).
  Overlays are never saved into output files.
* **Batch processing** - Start / Cancel, Test First 10, Test First 25,
  Process All; live progress (current file, counts, percentage); safe
  cancellation; the GUI stays responsive (all work runs on worker threads).
* **Manual review screen** - step through flagged photos, pan / zoom /
  rotate the crop, pick which face to use when several were detected, and
  Save Override (the corrected file is promoted into the `_crop` root).
* **Contact sheets** - paginated grids (30 per page) with the filename under
  each thumbnail, saved to `CONTACT_SHEETS\`.
* **CSV report** - filename, paths, status, face count, rotation, eye
  distance (px and ratio), blur score, detection confidence, processing
  time, and reasons.
* **Settings** - output width/height (default 600x800, 3:4), eye midpoint
  X/Y (default 50% / 40%), eye distance (default 34% of width), JPEG quality
  (default 95); persisted per user; Restore Defaults button. Advanced QA
  thresholds (blur, pose limits, headroom) live in the same `settings.json`.

## Technology

Python + [Flet](https://flet.dev) GUI + [MediaPipe Tasks](https://developers.google.com/mediapipe)
(FaceLandmarker with iris landmarks + BlazeFace detector, bundled locally in
`models/`) + OpenCV (all geometry and encoding) + NumPy + Pillow.

Notable engineering details:

* Eye centers are computed from the 5 iris landmarks per eye (eyelid-contour
  fallback), never a single point.
* Rotation + scale + translation are applied as **one** affine warp; large
  downscales first pass through INTER_AREA at the right resolution, then
  Lanczos finishes - the image is decoded once and encoded once.
* Head pose (yaw/pitch/roll) comes from MediaPipe's facial transformation
  matrix and feeds the REVIEW rules.
* Faces missed by the landmarker are rescued by re-running it on detector
  crops, and a last-resort region scan handles faces that are small relative
  to the frame. Sideways photos without EXIF orientation are auto-detected
  by retrying at 90/270/180 degrees.
* MediaPipe models load once per process and are reused for the whole batch.
  Images are processed one at a time - 2,000+ photos never sit in RAM.

## Development setup

Requires Python 3.11 or 3.12 (3.12.x tested; all dependencies also publish
3.11 wheels - see the pinned, verified set in `requirements.txt`).

```bat
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python main.py
```

On Windows you can simply run `run_windows.bat`, which does all of the above.

Useful entry points:

```bat
python main.py                                 :: desktop GUI
python main.py --web --port 8619               :: GUI in a web browser
python main.py --process C:\Photos\Employee_IDs --limit 10   :: headless batch
python main.py --selftest                      :: pipeline/model sanity check
```

### Tests

```bat
pip install -r requirements-dev.txt
python -m pytest
```

64 tests cover path safety (traversal, symlinks, sibling `_crop` creation),
filename/extension preservation, EXIF orientation, affine math, eye
placement on real crops (verified by re-detecting the face on the output),
corrupt/unsupported files, no-face and multiple-face classification, resume
modes, cancellation, contact sheets, and the bit-for-bit source-safety proof.

## Building the Windows application (developers only)

On a Windows 10/11 machine, run **one** script:

```bat
build_windows.bat
```

This produces everything end users need:

```
dist\installer\IDPhotoAutoCropper-Setup.exe    ← give users this (install + uninstall + upgrade)
dist\portable\IDPhotoAutoCropper.exe         ← optional single-file portable copy
```

Requires [Inno Setup 6](https://jrsoftware.org/isinfo.php) for the installer (free).
The target PC needs **no Python** — models, OpenCV, MediaPipe, and the GUI are all bundled.

### Automated builds (GitHub Releases)

Tag a release to build on GitHub's Windows runner (no local build machine needed):

```bat
git tag v1.0.1
git push origin v1.0.1
```

The workflow uploads `IDPhotoAutoCropper-Setup.exe` and `IDPhotoAutoCropper.exe`
to the release page. You can also trigger it manually from Actions → Build Windows.

## Privacy

* All processing is local; the app makes no network requests at runtime.
* No face recognition, no identity comparison, no biometric templates -
  landmarks are used transiently for geometric alignment only.
* The CSV report stores only geometric QA measurements.

## Project structure

```
main.py                  entry point (GUI, --web, --process, --selftest)
app/                     GUI (Flet), settings persistence, review screen
processing/              detector, landmarks, alignment, cropper, quality,
                         batch processor, contact sheets, debug overlay
utilities/               path safety, image IO, logging, CSV report
models/                  bundled MediaPipe models (offline)
assets/                  icon + bundled selftest portrait
packaging/               PyInstaller spec + Inno Setup installer script
tests/                   pytest suite (64 tests)
build_windows.bat        one-command Windows build (tests + exe + installer)
run_windows.bat          run from source on Windows
push_to_github.bat       push main to GitHub (after cloning locally)
```

## GitHub

Canonical repository: **https://github.com/skyemain/cropper**

If you cloned from Cursor's temporary Origin remote and need to push to GitHub:

```bat
push_to_github.bat
```

Or manually (requires Git):

```bat
git remote add github https://github.com/skyemain/cropper.git
git push -u github main
```

**No Git on your PC?** The cloud agent can push for you after a one-time GitHub
authorization (see agent instructions), or upload the source zip from the
agent artifacts at `cropper-source.zip` via
https://github.com/skyemain/cropper/upload/main
