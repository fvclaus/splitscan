import time
from pathlib import Path

import cv2
import numpy as np
import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox

from photo_splitter.domain import PhotoBoundary
from photo_splitter.main_window import MainWindow
from photo_splitter.preferences import Preferences
from photo_splitter.widgets.scan_view import ScanView
from photo_splitter.workers import Worker
from photo_splitter import telemetry


def wait_for_job(app, window):
    deadline = time.monotonic() + 10
    while window._working and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()
    assert not window._working


def test_main_window_has_splitscan_taskbar_icon(app):
    window = MainWindow()
    try:
        assert not window.windowIcon().isNull(), "SplitScan must set its taskbar/window icon"
        image = window.windowIcon().pixmap(64, 64).toImage()
        assert not image.isNull()
        assert image.pixelColor(8, 32).name() == "#286b58"
        assert image.pixelColor(32, 32).name() == "#ffffff"
    finally:
        window.close()


def test_import_preview_export_and_option_invalidation(app, tmp_path, monkeypatch):
    events = []
    monkeypatch.setattr(telemetry, "capture_usage", lambda *args: events.append(args))
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    monkeypatch.setattr(
        QMessageBox, "warning", lambda *args: (_ for _ in ()).throw(AssertionError(args[-1]))
    )
    image = np.full((350, 500, 3), 240, np.uint8)
    cv2.rectangle(image, (40, 40), (200, 280), (40, 100, 160), -1)
    cv2.rectangle(image, (270, 65), (460, 255), (120, 40, 80), -1)
    path = tmp_path / "scan.png"
    cv2.imwrite(str(path), image)
    source_bytes = path.read_bytes()
    window = MainWindow()
    window.show()
    app.processEvents()
    window._output_directory = tmp_path
    window._load_scan(path)
    wait_for_job(app, window)
    assert len(window._boundaries) == 2
    assert events == [("scan_loaded",)]
    window._redetect()
    wait_for_job(app, window)
    assert events == [("scan_loaded",)]
    window._start_preview()
    wait_for_job(app, window)
    assert len(window.photo_grid.items) == 2
    assert events == [("scan_loaded",), ("photos_extracted", 2)]
    window.photo_grid._checks[1].setChecked(False)
    window.view_mode.setCurrentIndex(1)
    assert window.photo_grid.selected_indices() == (0,)
    window._export_selected()
    wait_for_job(app, window)
    assert len(list(tmp_path.glob("*.jpg"))) == 1
    assert events == [("scan_loaded",), ("photos_extracted", 2), ("photos_saved", 1)]
    assert path.read_bytes() == source_bytes
    window.trim_borders.setChecked(False)
    assert not window.photo_grid.items
    assert not window.export_button.isEnabled()
    window.close()


def test_loupe_tracks_drag_and_escape_restores_corner(app):
    corrections = []
    view = ScanView()
    view.resize(620, 480)
    view.show()
    image = np.full((300, 400, 3), 240, np.uint8)
    boundary = PhotoBoundary(corners=((30, 30), (350, 30), (350, 250), (30, 250)))
    view.set_scan(image, (boundary,))
    view.boundary_corrected.connect(lambda: corrections.append(True))
    app.processEvents()
    corner = view._image_to_widget(30, 30).toPoint()
    QTest.mousePress(view, Qt.MouseButton.LeftButton, pos=corner)
    assert view._drag_corner == (0, 0)
    QTest.mouseMove(view, corner + QPoint(12, 8))
    app.processEvents()
    assert view._drag_current == QPointF(corner + QPoint(12, 8))
    assert view._loupe_factor == 3.0
    assert not view.grab().isNull()
    QTest.keyClick(view, Qt.Key.Key_Escape)
    assert view.boundaries[0].corners == boundary.corners
    assert view._drag_corner is None
    assert not corrections
    QTest.mousePress(view, Qt.MouseButton.LeftButton, pos=corner)
    QTest.mouseMove(view, corner + QPoint(9, 7))
    QTest.mouseRelease(view, Qt.MouseButton.LeftButton, pos=corner + QPoint(9, 7))
    assert view._drag_corner is None
    assert view._drag_current is None
    assert view.boundaries[0].user_confirmed
    assert corrections == [True]
    view.close()


@pytest.mark.parametrize("finish", ["release", "escape", "focus_loss", "unchanged", "invalid"])
def test_committed_border_correction_events(app, monkeypatch, finish):
    events = []
    monkeypatch.setattr(telemetry, "capture_usage", lambda *args: events.append(args))
    window = MainWindow()
    window.show()
    image = np.full((300, 400, 3), 240, np.uint8)
    boundary = PhotoBoundary(corners=((30, 30), (350, 30), (350, 250), (30, 250)))
    window._scan = image
    window.scan_view.set_scan(image, (boundary,))
    app.processEvents()
    view = window.scan_view
    corner = view._image_to_widget(30, 30).toPoint()
    QTest.mousePress(view, Qt.MouseButton.LeftButton, pos=corner)
    if finish != "unchanged":
        for offset in (QPoint(4, 3), QPoint(8, 5), QPoint(12, 8)):
            QTest.mouseMove(view, corner + offset)
        assert not events
    if finish == "escape":
        QTest.keyClick(view, Qt.Key.Key_Escape)
    elif finish == "focus_loss":
        window.settings_button.setFocus()
        app.processEvents()
    elif finish == "invalid":
        from dataclasses import replace
        view._boundaries[0] = replace(boundary, corners=((30, 30),) * 4)
        QTest.mouseRelease(view, Qt.MouseButton.LeftButton, pos=corner)
    else:
        QTest.mouseRelease(view, Qt.MouseButton.LeftButton, pos=corner + QPoint(12, 8))
    assert events == ([("boundary_corrected",)] if finish == "release" else [])
    window.close()


def test_confirmation_selection_failed_cancelled_and_stale_jobs_do_not_count(app, monkeypatch):
    from photo_splitter.domain import DetectionFailure
    from photo_splitter.widgets.photo_grid import PhotoPreview

    events = []
    monkeypatch.setattr(telemetry, "capture_usage", lambda *args: events.append(args))
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: None)
    window = MainWindow()
    image = np.full((300, 400, 3), 240, np.uint8)
    boundary = PhotoBoundary(
        corners=((30, 30), (350, 30), (350, 250), (30, 250)), needs_review=True
    )
    window._scan = image
    window.scan_view.set_scan(image, (boundary,))
    window.scan_view.confirm_selected_boundary()
    window._set_all_boundaries_selected(False)
    assert not events
    preview = PhotoPreview(boundary, image, 320, 220)
    window._active_token = 12
    window._job_kind = "extract"
    window._job_finished(11, (preview,))
    window._job_failed(12, "Failed")
    window._cancel_event.set()
    window._job_finished(12, (preview,))
    window._cancel_event.clear()
    window._job_finished(12, ())
    window._job_kind = "import"
    window._job_finished(12, (Path("private.png"), image, DetectionFailure("Failed")))
    assert not events
    window.close()


def test_preferences_survive_new_instance_and_reject_missing_directory(app, tmp_path):
    Preferences().set_output_directory(tmp_path)
    assert Preferences().output_directory() == tmp_path


def test_worker_errors_are_reported_and_stale_results_ignored(app):
    failures = []
    def fail():
        raise ValueError("visible failure")
    worker = Worker(7, fail)
    worker.signals.failed.connect(lambda token, reason: failures.append((token, reason)))
    worker.run()
    assert failures == [(7, "visible failure")]
    window = MainWindow()
    window._active_token = 8
    window._job_finished(7, ())
    assert not window.photo_grid.items
    window.close()


def test_cancelled_worker_emits_cancel_signal(app):
    from photo_splitter.domain import OperationCancelled
    outcomes = []
    def cancelled():
        raise OperationCancelled()
    worker = Worker(9, cancelled)
    worker.signals.cancelled.connect(outcomes.append)
    worker.run()
    assert outcomes == [9]


@pytest.mark.parametrize("left", [0, 100])
def test_loupe_pixels_are_magnified_three_times_without_edge_stretching(app, left):
    view = ScanView()
    view.resize(620, 480)
    view.show()
    image = np.full((300, 400, 3), 240, np.uint8)
    image[:, left + 5:left + 10] = (0, 0, 255)
    boundary = PhotoBoundary(corners=((left, 100), (350, 100), (350, 250), (left, 250)))
    view.set_scan(image, (boundary,))
    app.processEvents()
    point = view._image_to_widget(left, 100).toPoint()
    QTest.mousePress(view, Qt.MouseButton.LeftButton, pos=point)
    app.processEvents()
    screenshot = view.grab().toImage()
    center_x = point.x() + 26 + 74
    center_y = point.y() - 148 - 22 + 74
    if point.y() - 148 - 22 < 8:
        center_y = point.y() + 24 + 74
    row = center_y + 15
    red_columns = [
        column
        for column in range(center_x, center_x + 68)
        if screenshot.pixelColor(column, row).red() > 250
        and screenshot.pixelColor(column, row).green() < 10
    ]
    assert red_columns
    expected_width = 5 * view._scale * 3
    assert abs(len(red_columns) - expected_width) < 3
    QTest.keyClick(view, Qt.Key.Key_Escape)
    view.close()
