import cv2
import numpy as np

from photo_splitter.detection import detect_photos
from photo_splitter.domain import AmbiguousDetections, DetectionFailure, DetectionSuccess, NoDetections


def synthetic_scan() -> np.ndarray:
    image = np.full((500, 760, 3), 242, dtype=np.uint8)
    rectangles = [
        ((70, 70), (300, 210), (30, 80, 145)),
        ((420, 65), (690, 220), (110, 60, 30)),
        ((75, 285), (320, 445), (45, 130, 60)),
        ((430, 300), (680, 440), (90, 45, 130)),
    ]
    for top_left, bottom_right, color in rectangles:
        cv2.rectangle(image, top_left, bottom_right, color, thickness=-1)
        cv2.rectangle(image, top_left, bottom_right, (20, 20, 20), thickness=3)
    return image


def test_detects_discrete_photos_and_valid_corners() -> None:
    outcome = detect_photos(synthetic_scan())

    assert isinstance(outcome, DetectionSuccess)
    assert len(outcome.boundaries) == 4
    for boundary in outcome.boundaries:
        points = np.asarray(boundary.corners)
        assert points.shape == (4, 2)
        assert np.isfinite(points).all()


def test_uniform_scan_returns_no_detections() -> None:
    outcome = detect_photos(np.full((240, 320, 3), 240, dtype=np.uint8))

    assert isinstance(outcome, NoDetections)
    assert "No photo borders" in outcome.reason


def test_empty_and_invalid_threshold_are_explicit_failures() -> None:
    assert isinstance(detect_photos(np.empty((0, 0, 3), dtype=np.uint8)), DetectionFailure)
    assert isinstance(detect_photos(synthetic_scan(), threshold=0), DetectionFailure)


def test_touching_photos_are_split_and_require_review():
    image = np.full((500, 700, 3), 242, np.uint8)
    cv2.rectangle(image, (60, 60), (330, 260), (30, 80, 145), -1)
    cv2.rectangle(image, (330, 180), (620, 380), (110, 60, 30), -1)
    outcome = detect_photos(image)
    assert isinstance(outcome, AmbiguousDetections)
    assert len(outcome.boundaries) == 2
    assert all(boundary.needs_review for boundary in outcome.boundaries)


def test_rotated_photo_and_scan_edge_review():
    image = np.full((400, 600, 3), 242, np.uint8)
    corners = cv2.boxPoints(((300, 200), (240, 140), 17)).astype(np.int32)
    cv2.fillConvexPoly(image, corners, (40, 110, 170))
    outcome = detect_photos(image)
    assert isinstance(outcome, DetectionSuccess)
    assert len(outcome.boundaries) == 1
    image = np.full((400, 600, 3), 242, np.uint8)
    cv2.rectangle(image, (0, 50), (200, 300), (40, 110, 170), -1)
    assert isinstance(detect_photos(image), AmbiguousDetections)


def test_low_contrast_threshold_and_perspective_corners():
    image = np.full((400, 600, 3), 230, np.uint8)
    corners = np.array([[90, 60], [420, 85], [390, 320], [65, 290]], np.int32)
    cv2.fillConvexPoly(image, corners, (215, 215, 215))
    outcome = detect_photos(image, threshold=5)
    assert isinstance(outcome, DetectionSuccess)
    detected = np.asarray(outcome.boundaries[0].corners)
    assert np.max(np.min(np.linalg.norm(detected[:, None] - corners[None], axis=2), axis=1)) <= 3
