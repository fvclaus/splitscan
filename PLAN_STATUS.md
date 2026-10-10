# Photo splitter

## Goal

Split one flatbed scan containing several photos into individually deskewed, cropped JPEG files while preserving the original scan.

## Agreed scope

- Python desktop app with PySide6 UI, guided by the Keepsake workspace in Figma file `hdIkkiu6AL9aADv5U48HlG`, node `4:1077`.
- OpenCV contour detection first, with OpenCV watershed automatically attempted for likely touching-photo regions. Review watershed proposals before export. Keep a detector seam for future backends; SAM is deferred.
- Editable quadrilateral boundaries, add/select/deselect actions, corner-drag loupe at 3×, photo previews, auto-straighten and border-trim options.
- One input scan at a time. Remember one output folder between scans and app launches.
- Export selected photos as full-pixel-dimension JPEGs at encoder quality 100. Never overwrite existing files.
- Process images locally. Supported inputs: JPEG, PNG, TIFF, BMP.

## Implementation status

The initial application is implemented: OpenCV detection/watershed, crop/export, remembered settings, and the Qt workspace with an editable-boundary loupe. Automated image-processing and offscreen Qt workflow tests pass; desktop startup has also been smoke-tested. See [README.md](./README.md) for setup, usage, and limitations.

## Known tuning need

Synthetic fixtures provide repeatable tests, but detection thresholds still need validation against representative real flatbed scans.
