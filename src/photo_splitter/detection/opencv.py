from __future__ import annotations

import cv2
import numpy as np

from photo_splitter.domain import (
    AmbiguousDetections,
    DetectionFailure,
    DetectionOutcome,
    DetectionSuccess,
    NoDetections,
    PhotoBoundary,
)
from photo_splitter.detection.geometry import contour_boundary, validate_corners
from photo_splitter.detection.watershed import split_touching_region


class OpenCVPhotoDetector:
    def detect(self, image: np.ndarray, threshold: int = 18) -> DetectionOutcome:
        return detect_photos(image, threshold)


def detect_photos(image: np.ndarray, threshold: int = 18) -> DetectionOutcome:
    if image is None or not isinstance(image, np.ndarray) or image.size == 0:
        return DetectionFailure("The scan is empty or could not be decoded.")
    if image.ndim not in (2, 3) or (image.ndim == 3 and image.shape[2] not in (1, 3, 4)):
        return DetectionFailure("The scan has an unsupported pixel layout.")
    if not 1 <= threshold <= 80:
        return DetectionFailure("Detection threshold must be between 1 and 80.")

    try:
        bgr = _to_bgr8(image)
        height, width = bgr.shape[:2]
        if min(height, width) < 32:
            return DetectionFailure("The scan is too small to detect photographs.")
        lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
        background = _estimate_background(lab)
        distance = np.linalg.norm(lab - background[None, None, :], axis=2)
        mask = np.uint8(distance > threshold) * 255
        kernel_size = max(3, min((min(height, width) // 180) | 1, 11))
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_size, kernel_size))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    except cv2.error as exc:
        return DetectionFailure(f"OpenCV could not process the scan: {exc}")

    min_area = max(64.0, width * height * 0.002)
    candidates = [contour for contour in contours if cv2.contourArea(contour) >= min_area]
    candidates.sort(key=lambda contour: (cv2.boundingRect(contour)[1], cv2.boundingRect(contour)[0]))
    if not candidates:
        return NoDetections("No photo borders were detected. Try lowering the threshold.")

    boundaries: list[PhotoBoundary] = []
    diagnostics: list[str] = []
    for contour in candidates:
        _, _, box_width, box_height = cv2.boundingRect(contour)
        if min(box_width, box_height) < 20:
            continue
        perimeter = cv2.arcLength(contour, True)
        polygon = cv2.approxPolyDP(contour, 0.018 * perimeter, True)
        area = max(1.0, cv2.contourArea(contour))
        hull_area = max(1.0, cv2.contourArea(cv2.convexHull(contour)))
        solidity = area / hull_area
        if len(polygon) > 5 or solidity < 0.90:
            split = split_touching_region(bgr, mask, contour)
            if len(split) >= 2:
                boundaries.extend(split)
                diagnostics.append("Watershed proposed a split; review the boundaries.")
                continue
            diagnostics.append("An irregular region could not be split confidently.")
            boundary = contour_boundary(contour, confidence=0.48)
            boundaries.append(
                PhotoBoundary(
                    corners=boundary.corners,
                    confidence=boundary.confidence,
                    needs_review=True,
                )
            )
            continue

        boundary = contour_boundary(contour, confidence=min(0.98, max(0.65, solidity)))
        if validate_corners(boundary.corners, bgr.shape):
            points = np.asarray(boundary.corners)
            if (
                points[:, 0].min() <= 1
                or points[:, 1].min() <= 1
                or points[:, 0].max() >= width - 2
                or points[:, 1].max() >= height - 2
            ):
                boundary = PhotoBoundary(
                    corners=boundary.corners, confidence=0.5, needs_review=True
                )
                diagnostics.append("A photo touches the scan edge; review its boundary.")
            boundaries.append(boundary)

    if not boundaries:
        return NoDetections("No usable photo boundaries were detected.")
    if any(boundary.needs_review for boundary in boundaries):
        return AmbiguousDetections(
            boundaries=tuple(boundaries),
            reason="Review the proposed boundaries before extracting photos.",
            diagnostics=tuple(dict.fromkeys(diagnostics)),
        )
    return DetectionSuccess(tuple(boundaries), tuple(diagnostics))


def _to_bgr8(image: np.ndarray) -> np.ndarray:
    if image.dtype != np.uint8:
        image = cv2.normalize(image, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    if image.ndim == 2:
        return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    if image.shape[2] == 1:
        return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    if image.shape[2] == 4:
        return cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
    return image.copy()


def _estimate_background(lab: np.ndarray) -> np.ndarray:
    height, width = lab.shape[:2]
    strip = max(1, min(height, width) // 40)
    samples = np.concatenate(
        (
            lab[:strip].reshape(-1, 3),
            lab[-strip:].reshape(-1, 3),
            lab[:, :strip].reshape(-1, 3),
            lab[:, -strip:].reshape(-1, 3),
        ),
        axis=0,
    )
    return np.median(samples, axis=0)
