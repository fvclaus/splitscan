from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable
from pathlib import Path
import os
import tempfile

import cv2
import numpy as np

from photo_splitter.domain import OperationCancelled, PhotoBoundary
from photo_splitter.detection.geometry import validate_corners


SUPPORTED_INPUT_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"}
JPEG_QUALITY = 100


class ImageReadError(ValueError):
    pass


class ExportError(OSError):
    pass


@dataclass(frozen=True)
class ExportedPhoto:
    path: Path
    width: int
    height: int


def read_scan(path: Path) -> np.ndarray:
    if path.suffix.lower() not in SUPPORTED_INPUT_SUFFIXES:
        raise ImageReadError("Supported scan formats are JPEG, PNG, TIFF, and BMP.")
    try:
        encoded = np.fromfile(path, dtype=np.uint8)
    except OSError as exc:
        raise ImageReadError(f"Could not read {path.name}: {exc}") from exc
    if encoded.size == 0:
        raise ImageReadError(f"{path.name} is empty or unreadable.")
    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if image is None or image.size == 0:
        raise ImageReadError(
            f"Could not decode {path.name}. Supported scan formats are JPEG, PNG, TIFF, and BMP."
        )
    return image


def extract_photo(
    image: np.ndarray, boundary: PhotoBoundary, *, auto_straighten: bool = True, trim_borders: bool = True
) -> np.ndarray:
    if not validate_corners(boundary.corners, image.shape):
        raise ValueError("Photo boundary must have four valid corners inside the scan.")
    source = np.asarray(boundary.corners, dtype=np.float32)
    top_left, top_right, bottom_right, bottom_left = source
    width = max(
        1,
        int(round(max(np.linalg.norm(top_right - top_left), np.linalg.norm(bottom_right - bottom_left)))),
    )
    height = max(
        1,
        int(round(max(np.linalg.norm(bottom_left - top_left), np.linalg.norm(bottom_right - top_right)))),
    )
    destination = np.array(
        [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]],
        dtype=np.float32,
    )
    if auto_straighten:
        transform = cv2.getPerspectiveTransform(source, destination)
        crop = cv2.warpPerspective(image, transform, (width, height), flags=cv2.INTER_CUBIC)
    else:
        x, y, box_width, box_height = cv2.boundingRect(source.astype(np.int32))
        crop = image[y : y + box_height, x : x + box_width].copy()
    if trim_borders:
        crop = trim_uniform_border(crop)
    return crop


def trim_uniform_border(image: np.ndarray) -> np.ndarray:
    if image.size == 0 or min(image.shape[:2]) < 8:
        return image
    height, width = image.shape[:2]
    band = max(1, min(height, width) // 100)
    border = np.concatenate(
        (
            image[:band].reshape(-1, image.shape[2]),
            image[-band:].reshape(-1, image.shape[2]),
            image[:, :band].reshape(-1, image.shape[2]),
            image[:, -band:].reshape(-1, image.shape[2]),
        ),
        axis=0,
    )
    color = np.median(border, axis=0)
    difference = np.max(np.abs(image.astype(np.int16) - color.astype(np.int16)), axis=2)
    foreground = np.uint8(difference > 12) * 255
    points = cv2.findNonZero(foreground)
    if points is None:
        return image
    x, y, crop_width, crop_height = cv2.boundingRect(points)
    margin = max(1, min(height, width) // 200)
    left, top = max(0, x - margin), max(0, y - margin)
    right, bottom = min(width, x + crop_width + margin), min(height, y + crop_height + margin)
    if (right - left) * (bottom - top) < width * height * 0.55:
        return image
    return image[top:bottom, left:right].copy()


def export_photos(
    image: np.ndarray,
    boundaries: list[PhotoBoundary] | tuple[PhotoBoundary, ...],
    output_directory: Path,
    scan_stem: str,
    *,
    auto_straighten: bool = True,
    trim_borders: bool = True,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[ExportedPhoto, ...]:
    if not output_directory.exists() or not output_directory.is_dir():
        raise ExportError(f"Output folder does not exist: {output_directory}")
    selected = [boundary for boundary in boundaries if boundary.selected]
    if not selected:
        raise ExportError("Select at least one photo to export.")
    staged: list[tuple[Path, Path, int, int]] = []
    created: list[Path] = []
    try:
        for index, boundary in enumerate(selected, start=1):
            if cancelled is not None and cancelled():
                raise OperationCancelled("Export cancelled.")
            if boundary.needs_review and not boundary.user_confirmed:
                raise ExportError(f"Photo {index} has an unconfirmed boundary.")
            crop = extract_photo(
                image,
                boundary,
                auto_straighten=auto_straighten,
                trim_borders=trim_borders,
            )
            success, encoded = cv2.imencode(
                ".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]
            )
            if not success:
                raise ExportError(f"Could not encode photo {index} as JPEG.")
            with tempfile.NamedTemporaryFile(
                prefix=".photo-splitter-", suffix=".jpg", dir=output_directory, delete=False
            ) as stream:
                temporary_path = Path(stream.name)
                staged.append((temporary_path, _target_path(output_directory, scan_stem, index), crop.shape[1], crop.shape[0]))
                stream.write(encoded.tobytes())

        exported: list[ExportedPhoto] = []
        for temporary_path, target_path, width, height in staged:
            if cancelled is not None and cancelled():
                raise OperationCancelled("Export cancelled.")
            target_path = _link_unique(temporary_path, target_path)
            created.append(target_path)
            temporary_path.unlink()
            exported.append(ExportedPhoto(target_path, width, height))
        return tuple(exported)
    except (OSError, ValueError, cv2.error, OperationCancelled) as exc:
        for created_path in created:
            created_path.unlink(missing_ok=True)
        if isinstance(exc, (ExportError, OperationCancelled)):
            raise
        raise ExportError(f"Export failed: {exc}") from exc
    finally:
        for temporary_path, _, _, _ in staged:
            temporary_path.unlink(missing_ok=True)


def _target_path(directory: Path, scan_stem: str, index: int) -> Path:
    safe_stem = "".join(char if char.isalnum() or char in "-_ " else "_" for char in scan_stem).strip()
    return directory / f"{safe_stem or 'scan'}_photo_{index:03d}.jpg"


def _link_unique(source: Path, path: Path) -> Path:
    candidate = path
    suffix = 1
    while True:
        try:
            os.link(source, candidate)
            return candidate
        except FileExistsError:
            candidate = path.with_name(f"{path.stem}_{suffix}{path.suffix}")
            suffix += 1
