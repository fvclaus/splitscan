from __future__ import annotations

import cv2
import numpy as np

from photo_splitter.domain import PhotoBoundary
from photo_splitter.detection.geometry import contour_boundary


def split_touching_region(
    image: np.ndarray, mask: np.ndarray, contour: np.ndarray
) -> tuple[PhotoBoundary, ...]:
    x, y, width, height = cv2.boundingRect(contour)
    if width < 32 or height < 32:
        return ()

    region = np.zeros(mask.shape, dtype=np.uint8)
    cv2.drawContours(region, [contour], -1, 255, thickness=cv2.FILLED)
    region_crop = region[y : y + height, x : x + width]
    distance = cv2.distanceTransform(region_crop, cv2.DIST_L2, 5)
    max_distance = float(distance.max())
    if max_distance <= 0:
        return ()

    peak_mask = np.uint8(distance >= max_distance * 0.48)
    count, peak_labels = cv2.connectedComponents(peak_mask)
    if count < 3:
        return ()

    peaks: list[tuple[float, float, float]] = []
    for label in range(1, count):
        ys, xs = np.where(peak_labels == label)
        if len(xs) == 0:
            continue
        peaks.append((float(xs.mean()), float(ys.mean()), float(distance[ys, xs].max())))
    peaks.sort(key=lambda peak: peak[2], reverse=True)

    chosen: list[tuple[float, float, float]] = []
    separation = max(8.0, min(width, height) * 0.35)
    for peak in peaks:
        if all(
            np.hypot(peak[0] - prior[0], peak[1] - prior[1]) >= separation
            for prior in chosen
        ):
            chosen.append(peak)
        if len(chosen) == 4:
            break
    if len(chosen) < 2:
        return ()

    crop = image[y : y + height, x : x + width].copy()
    markers = np.zeros((height, width), dtype=np.int32)
    markers[region_crop == 0] = 1
    for index, (px, py, _) in enumerate(chosen, start=2):
        cv2.circle(
            markers,
            (int(round(px)), int(round(py))),
            max(2, int(min(width, height) * 0.035)),
            index,
            -1,
        )
    cv2.watershed(crop, markers)

    min_segment_area = cv2.contourArea(contour) * 0.12
    results: list[PhotoBoundary] = []
    for label in range(2, len(chosen) + 2):
        segment = np.uint8(markers == label) * 255
        contours, _ = cv2.findContours(segment, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            continue
        largest = max(contours, key=cv2.contourArea)
        if cv2.contourArea(largest) < min_segment_area:
            continue
        largest = largest.copy()
        largest[:, 0, 0] += x
        largest[:, 0, 1] += y
        boundary = contour_boundary(largest, confidence=0.58)
        results.append(
            PhotoBoundary(corners=boundary.corners, confidence=0.58, needs_review=True)
        )
    return tuple(results) if len(results) >= 2 else ()
