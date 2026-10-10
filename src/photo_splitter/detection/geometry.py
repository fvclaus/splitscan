from __future__ import annotations

import cv2
import numpy as np

from photo_splitter.domain import Corners, PhotoBoundary


def order_corners(points: np.ndarray) -> Corners:
    points = np.asarray(points, dtype=np.float32).reshape(4, 2)
    center = points.mean(axis=0)
    angles = np.arctan2(points[:, 1] - center[1], points[:, 0] - center[0])
    ordered = points[np.argsort(angles)]
    if cv2.contourArea(ordered.reshape(-1, 1, 2)) < 0:
        ordered = ordered[::-1]
    start = int(np.argmin(ordered.sum(axis=1)))
    ordered = np.roll(ordered, -start, axis=0)
    if ordered[1, 0] < ordered[-1, 0]:
        ordered = ordered[[0, 3, 2, 1]]
    a, b, c, d = ordered
    return (
        (float(a[0]), float(a[1])),
        (float(b[0]), float(b[1])),
        (float(c[0]), float(c[1])),
        (float(d[0]), float(d[1])),
    )


def contour_boundary(contour: np.ndarray, confidence: float = 0.9) -> PhotoBoundary:
    perimeter = cv2.arcLength(contour, True)
    polygon = cv2.approxPolyDP(contour, 0.018 * perimeter, True)
    if len(polygon) == 4 and cv2.isContourConvex(polygon):
        corners = order_corners(polygon.reshape(4, 2))
    else:
        rectangle = cv2.boxPoints(cv2.minAreaRect(contour))
        corners = order_corners(rectangle)
        confidence = min(confidence, 0.65)
    return PhotoBoundary(corners=corners, confidence=confidence, needs_review=confidence < 0.7)


def polygon_area(corners: Corners) -> float:
    points = np.asarray(corners, dtype=np.float32)
    return abs(float(cv2.contourArea(points.reshape(-1, 1, 2))))


def validate_corners(corners: Corners, image_shape: tuple[int, ...]) -> bool:
    points = np.asarray(corners, dtype=np.float32)
    if points.shape != (4, 2) or not np.isfinite(points).all():
        return False
    height, width = image_shape[:2]
    if np.any(points[:, 0] < 0) or np.any(points[:, 0] >= width):
        return False
    if np.any(points[:, 1] < 0) or np.any(points[:, 1] >= height):
        return False
    if polygon_area(corners) < max(16.0, width * height * 0.0005):
        return False
    edges = np.roll(points, -1, axis=0) - points
    return bool(
        np.all(np.linalg.norm(edges, axis=1) >= 2)
        and cv2.isContourConvex(points.reshape(-1, 1, 2))
    )
