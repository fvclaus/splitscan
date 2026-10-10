<p align="center">
  <img src="docs/assets/hero.svg" alt="SplitScan. Scan a page. Split it into photos." width="1200">
</p>

<p align="center">
  <strong>One flatbed scan. Individual photos. You stay in control of the edges.</strong><br>
  A local desktop application for detecting, reviewing, straightening, and exporting scanned photographs.
</p>

<p align="center">
  <a href="https://github.com/fvclaus/splitscan/releases/latest">Latest downloads</a> &nbsp;·&nbsp;
  <a href="#import-check-export">How it works</a> &nbsp;·&nbsp;
  <a href="#privacy">Privacy</a> &nbsp;·&nbsp;
  <a href="#run-from-source">Run from source</a>
</p>

> Downloads appear after the first successful tagged release. Portable builds target Windows x64,
> macOS Intel and Apple Silicon, and Linux x64. Download the archive for your platform,
> extract **all** its contents, and launch SplitScan; Python is not required.
> Keep the bundled libraries and notices beside the application.

![The SplitScan desktop workspace with a source scan and extracted photo previews](docs/assets/workspace.png)

## Import, check, export.

| 01 · Import a scan | 02 · Review the boundaries | 03 · Export individual files |
| --- | --- | --- |
| Scan several prints together, then import one JPEG, PNG, TIFF, or BMP. SplitScan detects candidate photo outlines. | If selected photos need attention, choose **Review boundaries**. Confirm each valid suggestion, drag corners to correct it, or exclude it. Invalid outlines require correction, not just confirmation. | Choose **Extract photos** to see previews and pixel dimensions, then export selected crops to a folder. Your original scan is never changed. |

**Fine-tune every edge.** Drag a corner to adjust an outline; a floating 3× loupe helps align it.
Use **Add boundary** for a missed photo. Click an outline to include or exclude it.
Review navigation does not change which photos you have included.
After the last review, extraction is available again; it does not start automatically.

**Navigate the canvas.**

| Action | Gesture |
| --- | --- |
| Pan | Hold **Space** and left-drag, or middle-mouse drag |
| Zoom | Mouse wheel or **Ctrl + wheel**, or the zoom buttons |
| Pan horizontally | **Shift + wheel** |
| Return to the whole scan | **Fit** |
| Cancel a corner drag | **Escape** |

Auto-straighten and border trimming are enabled by default. Changing boundaries or processing
options clears stale previews. Adjust edge sensitivity and re-detect if needed.
**Cancel processing** stops between processing stages, not during an OpenCV operation.
The output folder is remembered between scans and launches.

<img src="docs/assets/scanner.svg" alt="Use your scanner. Keep processing local. No photo uploads; the original scan stays intact." width="1000">

## Privacy

**All processing happens on device.** Scans and extracted photos are not uploaded.

Crash reporting is **optional and off by default**. If you enable it in the application,
sanitized error diagnostics are sent to Sentry: exception types, application stack locations,
application version, and operating system. Photos, image arrays, filenames, user paths,
exception messages, and sensitive breadcrumbs are stripped. Disable reporting at any time.
Network services can still observe connection metadata such as the source IP.

## Output and limitations

- JPEG exports use encoder quality **100**, without downscaling. Output pixel dimensions derive
  from the selected boundary. JPEG re-encoding is lossy; this is not lossless archival output.
- Existing files are never overwritten.
- OpenCV contour detection is primary; watershed attempts to split likely touching photos.
  Uncertain suggestions require explicit review. Difficult arrangements may need manual boundaries.
- One scan at a time. No SAM backend, multi-scan queue, or non-JPEG export.
- Large scans can require significant memory. Validate results against your real scans.
- Settings use Qt's platform-standard store. The legacy `Keepsake/PhotoSplitter` settings namespace
  is retained so existing output-folder and threshold preferences survive the rebrand.
- macOS downloads are not Developer ID signed or notarized. Gatekeeper may require an explicit
  per-app approval through macOS Privacy & Security after you verify the download.
  Windows may also warn about an unsigned application. Do not disable system-wide protections.

## Run from source

Use Python 3.11 or newer for the tested release build toolchain:

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test]'
photo-splitter
```

On Windows, activate with `.venv\Scripts\activate`.
The existing `photo-splitter` command and `photo_splitter` package name are intentionally retained.

With `uv`:

```sh
uv venv .venv
uv pip install --python .venv/bin/python -e '.[test]'
.venv/bin/photo-splitter
```

## Development and releases

```sh
pytest
photo-splitter --version
photo-splitter --smoke-test
```

Tests exercise detection, invalid/uncertain boundaries, guided review, editing and loupe behavior,
pan/zoom gestures, crop/export safety, settings, and telemetry sanitization.
Headless Qt tests use the offscreen platform; telemetry tests never send real events.

GitHub Actions validate pushes and pull requests with native builds and packaged smoke tests.
Version tags build release artifacts; publication is gated on successful builds and license checks.
The version is included in the app and download filenames.
See [distribution instructions](docs/DISTRIBUTION.md) for the supported build baseline,
packaging, license inventory, and shared-library replacement/source information.

## License

SplitScan's project-owned code and original README graphics are [MIT licensed](LICENSE),
© 2026 fvclaus and SplitScan contributors. Third-party components retain their own licenses,
including LGPL-covered PySide6/Qt. Downloads include third-party license notices and
corresponding-source information; the MIT license does not replace those obligations.
