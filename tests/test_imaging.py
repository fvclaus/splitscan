from pathlib import Path

import cv2
import numpy as np
import pytest

from photo_splitter.domain import OperationCancelled, PhotoBoundary
from photo_splitter.imaging import ExportError, extract_photo, export_photos, read_scan, trim_uniform_border


def scan() -> np.ndarray:
    image = np.full((180, 240, 3), 255, dtype=np.uint8)
    cv2.rectangle(image, (30, 25), (210, 155), (40, 100, 170), thickness=-1)
    return image


def boundary(selected: bool = True) -> PhotoBoundary:
    return PhotoBoundary(
        corners=((30, 25), (210, 25), (210, 155), (30, 155)),
        selected=selected,
        user_confirmed=True,
    )


def test_perspective_crop_keeps_source_pixel_size() -> None:
    result = extract_photo(scan(), boundary(), trim_borders=False)

    assert result.shape[:2] == (130, 180)


def test_export_writes_full_resolution_jpeg_and_never_overwrites(tmp_path: Path) -> None:
    first = export_photos(scan(), (boundary(),), tmp_path, "family_scan")
    second = export_photos(scan(), (boundary(),), tmp_path, "family_scan")

    assert first[0].path.name == "family_scan_photo_001.jpg"
    assert second[0].path.name == "family_scan_photo_001_1.jpg"
    decoded = cv2.imread(str(first[0].path))
    assert decoded is not None
    assert decoded.shape[:2] == (130, 180)
    assert first[0].path.read_bytes().startswith(b"\xff\xd8")


def test_export_rejects_unconfirmed_watershed_boundary(tmp_path: Path) -> None:
    proposed = PhotoBoundary(corners=boundary().corners, needs_review=True)

    with pytest.raises(ExportError, match="unconfirmed"):
        export_photos(scan(), (proposed,), tmp_path, "scan")


def test_read_scan_rejects_unsupported_format(tmp_path: Path) -> None:
    path = tmp_path / "scan.gif"
    path.write_bytes(b"not an image")

    with pytest.raises(ValueError, match="Supported scan formats"):
        read_scan(path)


def test_cancelled_export_cleans_staged_and_completed_files(tmp_path, monkeypatch):
    import photo_splitter.imaging as imaging
    calls = 0
    original_link = imaging._link_unique
    cancelled = False
    def link_and_cancel(source, target):
        nonlocal calls, cancelled
        result = original_link(source, target)
        calls += 1
        cancelled = True
        return result
    monkeypatch.setattr(imaging, "_link_unique", link_and_cancel)
    with pytest.raises(OperationCancelled):
        export_photos(scan(), (boundary(), boundary()), tmp_path, "scan", cancelled=lambda: cancelled)
    assert calls == 1
    assert list(tmp_path.iterdir()) == []


def test_invalid_nonconvex_boundary_is_rejected():
    crossed = PhotoBoundary(corners=((30, 25), (210, 155), (210, 25), (30, 155)))
    with pytest.raises(ValueError, match="four valid corners"):
        extract_photo(scan(), crossed)


def test_encoding_quality_is_maximum(tmp_path, monkeypatch):
    original = cv2.imencode
    settings = []
    def record(extension, image, parameters):
        settings.append(parameters)
        return original(extension, image, parameters)
    monkeypatch.setattr(cv2, "imencode", record)
    export_photos(scan(), (boundary(),), tmp_path, "scan")
    assert settings == [[cv2.IMWRITE_JPEG_QUALITY, 100]]


def test_border_trim_removes_only_uniform_outer_margin():
    image = np.full((100, 100, 3), 255, np.uint8)
    image[10:90, 10:90] = (40, 100, 160)
    result = trim_uniform_border(image)
    assert result.shape == (82, 82, 3)
    assert np.array_equal(result[1:-1, 1:-1], image[10:90, 10:90])


def test_corrupt_supported_input_reports_decode_error(tmp_path):
    path = tmp_path / "broken.png"
    path.write_bytes(b"not an image")
    with pytest.raises(ValueError, match="Could not decode"):
        read_scan(path)
