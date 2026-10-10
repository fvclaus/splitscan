# Keepsake Photo Splitter

A local desktop application for separating photos from a flatbed scan. The app detects photo borders, lets you adjust their corners, previews the rectified photos, and exports selected crops as high-quality JPEGs. Images are processed on your device; scans are not uploaded.

## Run

Python 3.10 or newer is required.

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test]'
photo-splitter
```

On Windows, activate the virtual environment with `.venv\Scripts\activate`.

If Python has no pip/venv support but `uv` is available:

```sh
uv venv .venv
uv pip install --python .venv/bin/python -e '.[test]'
.venv/bin/photo-splitter
```

## Workflow

1. Import one JPEG, PNG, TIFF, or BMP scan.
2. Review the detected outlines. Adjust a corner by dragging it; a floating 3× loupe follows the pointer during the drag to help align the boundary to the photo edge. Release to close the loupe.
3. Use **Add boundary** and drag a rectangle to include a missed photo. Click an outline to select or deselect it. Adjust edge sensitivity and re-detect if needed.
4. Click **Extract selected photos** to see the crop previews and pixel dimensions. For watershed suggestions, inspect the dashed boundaries and confirm or adjust them before export.
5. Choose an output folder once. The app remembers it between scans and launches. Exported names follow scan order; existing files are never overwritten.

Use the mouse wheel to zoom the scan, **Fit** to return to the full scan, and middle-mouse drag to pan when zoomed. Press **Escape** to cancel a boundary drag and restore its original position. **Cancel processing** cancels between processing stages; it cannot interrupt an OpenCV operation already running.

## Output and limitations

- Exports are JPEG at encoder quality 100 with no downscaling. The crop's output size is derived from the detected scan boundary. JPEG re-encoding is lossy even at maximum quality.
- Auto-straighten and border trimming are enabled by default and can be turned off.
- OpenCV contour detection is the primary detector. OpenCV watershed automatically attempts to split likely merged regions; proposed splits require user review. Watershed cannot resolve every touching-photo arrangement, so use the editable boundaries for correction.
- The app processes one source scan at a time. SAM, multi-scan queues, and non-JPEG export are not part of this version.
- Preferences use Qt's platform-standard `QSettings` store (on Linux, typically `~/.config/Keepsake/PhotoSplitter.conf`). A missing saved output folder must be chosen again before exporting.
- Supported inputs are JPEG, PNG, TIFF, and BMP. Very large scans can require significant memory.

## Development

Run tests with:

```sh
pytest
```

The tests cover discrete/rotated/touching-photo detection, uncertain scan-edge boundaries, no-detection/error outcomes, crop dimensions, JPEG quality, collision-safe filenames, cancellation cleanup, settings persistence, and the Qt import/edit/loupe/preview/export workflow. Headless Qt tests use the offscreen platform. Real scans should also be used to validate detection thresholds before relying on them for important archives.
