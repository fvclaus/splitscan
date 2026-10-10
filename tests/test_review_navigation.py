import numpy as np
import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest

from photo_splitter.domain import AmbiguousDetections, DetectionSuccess, PhotoBoundary
from photo_splitter.main_window import MainWindow
from photo_splitter.widgets.scan_view import ScanView


@pytest.mark.parametrize("space", [False, True])
def test_pan_preserves_boundaries(app, space):
    view = ScanView()
    view.resize(620, 480)
    view.show()
    boundary = PhotoBoundary(corners=((30, 30), (350, 30), (350, 250), (30, 250)))
    view.set_scan(np.full((300, 400, 3), 240, np.uint8), (boundary,))
    view.zoom_by(2)
    app.processEvents()
    before = QPointF(view._pan)
    button = Qt.MouseButton.LeftButton if space else Qt.MouseButton.MiddleButton
    if space:
        QTest.keyPress(view, Qt.Key.Key_Space)
    QTest.mousePress(view, button, pos=QPoint(300, 220))
    QTest.mouseMove(view, QPoint(340, 250))
    QTest.mouseRelease(view, button, pos=QPoint(340, 250))
    if space:
        QTest.keyRelease(view, Qt.Key.Key_Space)
    assert view._pan - before == QPointF(40, 30)
    assert view.boundaries == (boundary,)
    assert view._zoom == 2
    assert not view._panning
    view.close()


def test_shift_wheel_pans_without_zoom(app):
    view = ScanView()
    view.set_scan(np.zeros((300, 400, 3), np.uint8), ())
    event = QWheelEvent(
        QPointF(100, 100), QPointF(100, 100), QPoint(), QPoint(0, 120),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.ShiftModifier,
        Qt.ScrollPhase.NoScrollPhase, False,
    )
    view.wheelEvent(event)
    assert view._pan == QPointF(40, 0)
    assert view._zoom == 1
    view.close()


def test_guided_review_before_extraction(app, tmp_path):
    window = MainWindow()
    window.show()
    path = tmp_path / "scan.png"
    path.write_bytes(b"fixture")
    boundaries = tuple(
        PhotoBoundary(corners=((x, 30), (x + 100, 30), (x + 100, 250), (x, 250)),
                      needs_review=True)
        for x in (30, 200)
    )
    window._accept_scan(path, np.full((300, 400, 3), 240, np.uint8),
                        AmbiguousDetections(boundaries, "Review suggestions"))
    assert window.extract_button.text() == "Review 2 boundaries"
    window._start_preview()
    assert not window._working
    assert window.scan_view.boundaries == boundaries
    window._confirm_boundary()
    assert window.scan_view.selected_boundary_index == 1
    assert window.extract_button.text() == "Review 1 boundary"
    window._confirm_boundary()
    assert window.extract_button.text() == "Extract 2 photos"
    assert not window._working
    assert all(item.selected for item in window._boundaries)
    window.close()


def test_invalid_boundary_cannot_be_confirmed(app):
    view = ScanView()
    boundary = PhotoBoundary(corners=((-10, 30), (200, 30), (200, 250), (-10, 250)),
                             needs_review=True)
    view.set_scan(np.zeros((300, 400, 3), np.uint8), (boundary,))
    view.confirm_selected_boundary()
    assert view.boundaries == (boundary,)
    view.close()


def test_review_exclusion_and_reinclusion(app, tmp_path):
    window = MainWindow()
    path = tmp_path / "scan.png"
    path.write_bytes(b"fixture")
    boundary = PhotoBoundary(corners=((30, 30), (200, 30), (200, 250), (30, 250)),
                             needs_review=True)
    window._accept_scan(path, np.zeros((300, 400, 3), np.uint8),
                        AmbiguousDetections((boundary,), "Review"))
    window._start_preview()
    window._exclude_review_boundary()
    assert not window._boundaries[0].selected
    assert not window.extract_button.isEnabled()
    window._set_all_boundaries_selected(True)
    assert window.extract_button.text() == "Review 1 boundary"
    window.close()


def test_space_release_mid_drag_and_focus_loss(app):
    view = ScanView()
    view.show()
    view.set_scan(np.zeros((300, 400, 3), np.uint8), ())
    QTest.keyPress(view, Qt.Key.Key_Space)
    QTest.mousePress(view, Qt.MouseButton.LeftButton, pos=QPoint(200, 150))
    QTest.keyRelease(view, Qt.Key.Key_Space)
    QTest.mouseMove(view, QPoint(220, 160))
    QTest.mouseRelease(view, Qt.MouseButton.LeftButton, pos=QPoint(220, 160))
    assert view._pan == QPointF(20, 10)
    assert not view._space_pan
    QTest.keyPress(view, Qt.Key.Key_Space)
    from PySide6.QtGui import QFocusEvent
    from PySide6.QtCore import QEvent
    view.focusOutEvent(QFocusEvent(QEvent.Type.FocusOut))
    assert not view._space_pan and not view._panning
    view.close()


def test_click_corner_without_edit_does_not_confirm(app):
    view = ScanView()
    view.show()
    boundary = PhotoBoundary(corners=((30, 30), (200, 30), (200, 250), (30, 250)),
                             needs_review=True)
    view.set_scan(np.zeros((300, 400, 3), np.uint8), (boundary,))
    point = view._image_to_widget(30, 30).toPoint()
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=point)
    assert view.boundaries == (boundary,)
    view.close()


def test_invalid_outline_can_be_repaired_in_stages(app):
    view = ScanView()
    view.resize(620, 480)
    view.show()
    boundary = PhotoBoundary(corners=((-10, 30), (200, 30), (200, 250), (-10, 250)),
                             needs_review=True)
    view.set_scan(np.zeros((300, 400, 3), np.uint8), (boundary,))
    app.processEvents()
    for old, new in [((-10, 30), (15, 30)), ((-10, 250), (15, 250))]:
        start = view._image_to_widget(*old).toPoint()
        end = view._image_to_widget(*new).toPoint()
        QTest.mousePress(view, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(view, end)
        QTest.mouseRelease(view, Qt.MouseButton.LeftButton, pos=end)
        if old[1] == 30:
            assert not view.boundaries[0].user_confirmed
    assert view.boundaries[0].user_confirmed
    view.close()


def test_review_edit_advances_only_after_release_and_escape_restores(app, tmp_path):
    window = MainWindow()
    window.show()
    app.processEvents()
    path = tmp_path / "scan.png"
    path.write_bytes(b"fixture")
    boundaries = tuple(
        PhotoBoundary(corners=((x, 30), (x + 100, 30), (x + 100, 250), (x, 250)),
                      needs_review=True)
        for x in (30, 200)
    )
    window._accept_scan(path, np.zeros((300, 400, 3), np.uint8),
                        AmbiguousDetections(boundaries, "Review"))
    window._start_preview()
    point = window.scan_view._image_to_widget(30, 30).toPoint()
    QTest.mousePress(window.scan_view, Qt.MouseButton.LeftButton, pos=point)
    QTest.mouseMove(window.scan_view, point + QPoint(10, 5))
    assert window.scan_view.selected_boundary_index == 0
    QTest.keyClick(window.scan_view, Qt.Key.Key_Escape)
    assert window._boundaries == boundaries
    QTest.mousePress(window.scan_view, Qt.MouseButton.LeftButton, pos=point)
    QTest.mouseMove(window.scan_view, point + QPoint(10, 5))
    QTest.mouseRelease(window.scan_view, Qt.MouseButton.LeftButton, pos=point + QPoint(10, 5))
    assert window.scan_view.selected_boundary_index == 1
    window.close()


@pytest.mark.parametrize("modifier", [
    Qt.KeyboardModifier.ControlModifier,
    Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
])
def test_wheel_zoom_preserved(app, modifier):
    view = ScanView()
    view.set_scan(np.zeros((300, 400, 3), np.uint8), ())
    event = QWheelEvent(
        QPointF(100, 100), QPointF(100, 100), QPoint(), QPoint(0, 120),
        Qt.MouseButton.NoButton, modifier, Qt.ScrollPhase.NoScrollPhase, False,
    )
    view.wheelEvent(event)
    assert view._zoom == 1.12
    assert view._pan == QPointF()
    view.fit_scan()
    assert view._zoom == 1
    view.close()


@pytest.mark.parametrize("pixel,angle,modifier,expected", [
    (QPoint(), QPoint(0, 120), Qt.KeyboardModifier.NoModifier, QPointF(0, 40)),
    (QPoint(), QPoint(0, -120), Qt.KeyboardModifier.NoModifier, QPointF(0, -40)),
    (QPoint(0, 17), QPoint(0, 120), Qt.KeyboardModifier.NoModifier, QPointF(0, 17)),
    (QPoint(0, -17), QPoint(0, -120), Qt.KeyboardModifier.NoModifier, QPointF(0, -17)),
    (QPoint(), QPoint(120, 0), Qt.KeyboardModifier.NoModifier, QPointF(40, 0)),
    (QPoint(8, 17), QPoint(), Qt.KeyboardModifier.NoModifier, QPointF(8, 17)),
    (QPoint(), QPoint(0, -120), Qt.KeyboardModifier.ShiftModifier, QPointF(-40, 0)),
    (QPoint(0, 17), QPoint(0, 120), Qt.KeyboardModifier.ShiftModifier, QPointF(17, 0)),
    (QPoint(), QPoint(120, 0), Qt.KeyboardModifier.ShiftModifier, QPointF(40, 0)),
    (QPoint(), QPoint(), Qt.KeyboardModifier.NoModifier, QPointF()),
])
def test_wheel_scrolls_without_zoom_or_boundary_changes(app, pixel, angle, modifier, expected):
    view = ScanView()
    boundary = PhotoBoundary(corners=((30, 30), (350, 30), (350, 250), (30, 250)))
    view.set_scan(np.zeros((300, 400, 3), np.uint8), (boundary,))
    view.zoom_by(2)
    before = QPointF(view._pan)
    event = QWheelEvent(
        QPointF(100, 100), QPointF(100, 100), pixel, angle,
        Qt.MouseButton.NoButton, modifier, Qt.ScrollPhase.NoScrollPhase, False,
    )
    app.sendEvent(view, event)
    assert view._pan - before == expected
    assert view._zoom == 2
    assert view.boundaries == (boundary,)
    assert event.isAccepted()
    view.close()


def test_busy_controls_and_branding(app):
    window = MainWindow()
    assert window.windowTitle() == "SplitScan"
    assert window.privacy_label.text() == "All processing happens on device"
    window._working = True
    window._update_controls()
    assert not window.extract_button.isEnabled()
    assert not window.scan_view.isEnabled()
    window._working = False
    window.close()


def test_scan_replacement_resets_review_and_hand_mode(app, tmp_path):
    window = MainWindow()
    path = tmp_path / "scan.png"
    path.write_bytes(b"fixture")
    boundary = PhotoBoundary(corners=((30, 30), (200, 30), (200, 250), (30, 250)),
                             needs_review=True)
    image = np.zeros((300, 400, 3), np.uint8)
    window._accept_scan(path, image, AmbiguousDetections((boundary,), "Review"))
    window._start_preview()
    window.scan_view.begin_add_boundary()
    QTest.keyPress(window.scan_view, Qt.Key.Key_Space)
    window._accept_scan(path, image, DetectionSuccess((boundary.confirmed(),)))
    assert not window._reviewing
    assert not window.scan_view._space_pan
    assert not window.scan_view._add_mode
    assert window.extract_button.text() == "Extract 1 photo"
    assert window.confirm_boundary_button.isHidden()
    window.close()
