from __future__ import annotations

import math
from dataclasses import replace

import cv2
import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from photo_splitter.domain import Corners, PhotoBoundary
from photo_splitter.detection.geometry import validate_corners


class ScanView(QWidget):
    boundaries_changed = Signal(object)
    selection_changed = Signal()
    edit_rejected = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(420, 320)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._image: np.ndarray | None = None
        self._qimage: QImage | None = None
        self._boundaries: list[PhotoBoundary] = []
        self._scale = 1.0
        self._zoom = 1.0
        self._pan = QPointF(0, 0)
        self._selected = -1
        self._drag_corner: tuple[int, int] | None = None
        self._drag_start: QPointF | None = None
        self._drag_current: QPointF | None = None
        self._add_mode = False
        self._panning = False
        self._space_pan = False
        self._pan_button = Qt.MouseButton.NoButton
        self._last_mouse = QPointF()
        self._loupe_factor = 3.0
        self._original_boundary: PhotoBoundary | None = None
        self.setStyleSheet("background: #e9ede9;")

    @property
    def boundaries(self) -> tuple[PhotoBoundary, ...]:
        return tuple(self._boundaries)

    @property
    def image(self) -> np.ndarray | None:
        return self._image

    @property
    def selected_boundary_index(self) -> int:
        return self._selected

    @property
    def editing_boundary(self) -> bool:
        return self._drag_corner is not None

    def set_scan(self, image: np.ndarray, boundaries: tuple[PhotoBoundary, ...]) -> None:
        self._add_mode = False
        self._stop_pan()
        self._image = image
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        height, width = rgb.shape[:2]
        self._qimage = QImage(rgb.data, width, height, rgb.strides[0], QImage.Format.Format_RGB888).copy()
        self._boundaries = list(boundaries)
        self._selected = 0 if boundaries else -1
        self._zoom = 1.0
        self._pan = QPointF()
        self._drag_corner = None
        self._drag_start = None
        self._drag_current = None
        self._original_boundary = None
        self.fit_scan()
        self.update()
        self.boundaries_changed.emit(self.boundaries)

    def set_boundaries(self, boundaries: tuple[PhotoBoundary, ...]) -> None:
        self._boundaries = list(boundaries)
        self._selected = min(self._selected, len(self._boundaries) - 1)
        self.update()

    def confirm_selected_boundary(self) -> None:
        if 0 <= self._selected < len(self._boundaries):
            if self._image is None or not validate_corners(
                self._boundaries[self._selected].corners, self._image.shape
            ):
                self.edit_rejected.emit("Adjust the boundary to a valid outline inside the scan.")
                return
            self._boundaries[self._selected] = self._boundaries[self._selected].confirmed()
            self.boundaries_changed.emit(self.boundaries)
            self.update()

    def activate_boundary(self, boundary_id: str) -> None:
        for index, boundary in enumerate(self._boundaries):
            if boundary.boundary_id == boundary_id:
                self._selected = index
                center = QPointF(
                    sum(point[0] for point in boundary.corners) / 4,
                    sum(point[1] for point in boundary.corners) / 4,
                )
                self._pan += QPointF(self.width() / 2, self.height() / 2) - self._image_to_widget(
                    center.x(), center.y()
                )
                self.selection_changed.emit()
                self.update()
                return
        raise ValueError("Review boundary no longer exists.")

    def _restore_cursor(self) -> None:
        self.setCursor(
            Qt.CursorShape.OpenHandCursor if self._space_pan else
            Qt.CursorShape.CrossCursor if self._add_mode else Qt.CursorShape.ArrowCursor
        )

    def _stop_pan(self) -> None:
        self._panning = False
        self._space_pan = False
        self._pan_button = Qt.MouseButton.NoButton
        self._restore_cursor()

    def fit_scan(self) -> None:
        if self._image is None:
            return
        height, width = self._image.shape[:2]
        self._scale = min(
            max(0.0001, (self.width() - 32) / width),
            max(0.0001, (self.height() - 32) / height),
        )
        self._zoom = 1.0
        self._pan = QPointF()
        self.update()

    def zoom_by(self, factor: float) -> None:
        if self._image is None:
            return
        self._zoom = min(8.0, max(0.15, self._zoom * factor))
        self.update()

    def begin_add_boundary(self) -> None:
        if self._image is not None:
            self._add_mode = True
            self.setCursor(Qt.CursorShape.CrossCursor)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._image is not None and self._drag_corner is None and self._zoom == 1.0:
            self.fit_scan()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#e9ede9"))
        if self._qimage is None or self._image is None:
            painter.setPen(QColor("#69716c"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Import a scan to get started")
            return

        target = self._target_rect()
        painter.drawImage(target, self._qimage)
        scale = self._scale * self._zoom
        for index, boundary in enumerate(self._boundaries):
            points = [self._image_to_widget(x, y) for x, y in boundary.corners]
            path = QPainterPath(points[0])
            for point in points[1:]:
                path.lineTo(point)
            path.closeSubpath()
            active = index == self._selected
            color = QColor("#286b58") if boundary.selected else QColor("#89918b")
            pen = QPen(color, 2.5 if active else 1.5)
            requires_review = boundary.needs_review or not validate_corners(
                boundary.corners, self._image.shape
            )
            if requires_review:
                pen.setStyle(Qt.PenStyle.DashLine)
                pen.setColor(QColor("#bd6b2b"))
            painter.setPen(pen)
            painter.setBrush(
                QColor(40, 107, 88, 24) if boundary.selected else Qt.BrushStyle.NoBrush
            )
            painter.drawPath(path)
            for number, point in enumerate(points):
                radius = 6 if active else 4
                painter.setPen(QPen(Qt.GlobalColor.white, 1))
                painter.setBrush(color)
                painter.drawEllipse(point, radius, radius)
                if active and requires_review and number == 0:
                    painter.setPen(QColor("#8a451c"))
                    painter.drawText(point + QPointF(8, -8), "Review")

        if self._add_mode and self._drag_start is not None and self._drag_current is not None:
            painter.setPen(QPen(QColor("#286b58"), 2, Qt.PenStyle.DashLine))
            painter.setBrush(QColor(40, 107, 88, 28))
            painter.drawRect(QRectF(self._drag_start, self._drag_current).normalized())

        if self._drag_corner is not None and self._drag_current is not None:
            self._draw_loupe(painter, scale)

    def _draw_loupe(self, painter: QPainter, scale: float) -> None:
        if self._qimage is None or self._drag_current is None or self._drag_corner is None:
            return
        diameter = 148.0
        target = self._drag_current
        loupe = QRectF(target.x() + 26, target.y() - diameter - 22, diameter, diameter)
        if loupe.right() > self.width() - 8:
            loupe.moveLeft(target.x() - diameter - 26)
        if loupe.top() < 8:
            loupe.moveTop(target.y() + 24)
        loupe.moveLeft(min(self.width() - diameter - 8, max(8, loupe.left())))
        loupe.moveTop(min(self.height() - diameter - 8, max(8, loupe.top())))

        boundary_index, corner_index = self._drag_corner
        source_x = self._boundaries[boundary_index].corners[corner_index]
        magnification = scale * self._loupe_factor
        painter.save()
        circle = QPainterPath()
        circle.addEllipse(loupe)
        painter.setClipPath(circle)
        painter.fillRect(loupe, Qt.GlobalColor.white)
        image_rect = QRectF(
            loupe.center().x() - source_x[0] * magnification,
            loupe.center().y() - source_x[1] * magnification,
            self._qimage.width() * magnification,
            self._qimage.height() * magnification,
        )
        painter.drawImage(image_rect, self._qimage)
        painter.setPen(QPen(QColor("#286b58"), 1))
        center = loupe.center()
        painter.drawLine(QPointF(loupe.left(), center.y()), QPointF(loupe.right(), center.y()))
        painter.drawLine(QPointF(center.x(), loupe.top()), QPointF(center.x(), loupe.bottom()))
        painter.restore()
        painter.setPen(QPen(QColor("#286b58"), 3))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(loupe)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(loupe.adjusted(0, 0, 0, -8), Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter, "3×")

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self._image is None:
            return
        position = event.position()
        self._last_mouse = position
        self.setFocus()
        if self._drag_corner is None and self._drag_start is None and (
            event.button() == Qt.MouseButton.MiddleButton
            or (event.button() == Qt.MouseButton.LeftButton and self._space_pan)
        ):
            self._panning = True
            self._pan_button = event.button()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._add_mode:
            self._drag_start = position
            self._drag_current = position
            return

        hit = self._hit_corner(position)
        if hit is not None:
            self._selected, corner = hit
            self._original_boundary = self._boundaries[self._selected]
            self._drag_corner = (self._selected, corner)
            self._drag_current = position
            self.selection_changed.emit()
            self.update()
            return
        selected = self._hit_boundary(position)
        if selected is not None:
            if selected == self._selected:
                current = self._boundaries[selected]
                self._boundaries[selected] = PhotoBoundary(
                    corners=current.corners,
                    confidence=current.confidence,
                    selected=not current.selected,
                    needs_review=current.needs_review,
                    user_confirmed=current.user_confirmed,
                    boundary_id=current.boundary_id,
                )
            else:
                current = self._boundaries[selected]
                self._boundaries[selected] = PhotoBoundary(
                    corners=current.corners,
                    confidence=current.confidence,
                    selected=True,
                    needs_review=current.needs_review,
                    user_confirmed=current.user_confirmed,
                    boundary_id=current.boundary_id,
                )
            self._selected = selected
            self.boundaries_changed.emit(self.boundaries)
            self.selection_changed.emit()
        self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        position = event.position()
        if self._panning:
            self._pan += position - self._last_mouse
            self._last_mouse = position
        elif self._drag_corner is not None:
            self._drag_current = position
            boundary_index, corner_index = self._drag_corner
            boundary = self._boundaries[boundary_index]
            corners = list(boundary.corners)
            x, y = self._widget_to_image(position.x(), position.y())
            height, width = self._image.shape[:2]
            corners[corner_index] = (min(width - 1.0, max(0.0, x)), min(height - 1.0, max(0.0, y)))
            a, b, c, d = corners
            updated = (a, b, c, d)
            if validate_corners(updated, self._image.shape):
                self._boundaries[boundary_index] = boundary.with_corners(updated)
                self.boundaries_changed.emit(self.boundaries)
            elif self._original_boundary is not None and not validate_corners(
                self._original_boundary.corners, self._image.shape
            ):
                self._boundaries[boundary_index] = replace(
                    boundary, corners=updated, needs_review=True, user_confirmed=False
                )
                self.boundaries_changed.emit(self.boundaries)
                self.edit_rejected.emit("Continue adjusting: this outline is not yet valid.")
            else:
                self.edit_rejected.emit("Keep the boundary convex with four distinct corners.")
        elif self._add_mode and self._drag_start is not None:
            self._drag_current = position
        else:
            self._drag_current = None
            self._last_mouse = position
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._panning:
            if event.button() == self._pan_button:
                self._panning = False
                self._pan_button = Qt.MouseButton.NoButton
                self._restore_cursor()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._drag_corner is not None:
            index, _ = self._drag_corner
            changed = self._boundaries[index] != self._original_boundary
            valid = validate_corners(self._boundaries[index].corners, self._image.shape)
            if changed and valid:
                self._boundaries[index] = self._boundaries[index].confirmed()
            self._drag_corner = None
            self._original_boundary = None
            self._drag_current = None
            self.boundaries_changed.emit(self.boundaries)
        elif event.button() == Qt.MouseButton.LeftButton and self._add_mode:
            start = self._drag_start
            current = event.position()
            self._drag_start = None
            self._drag_current = None
            self._add_mode = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            if start is not None:
                left, right = sorted((start.x(), current.x()))
                top, bottom = sorted((start.y(), current.y()))
                a = self._widget_to_image(left, top)
                b = self._widget_to_image(right, bottom)
                height, width = self._image.shape[:2]
                a = (max(0.0, min(width - 1.0, a[0])), max(0.0, min(height - 1.0, a[1])))
                b = (max(0.0, min(width - 1.0, b[0])), max(0.0, min(height - 1.0, b[1])))
                if abs(b[0] - a[0]) >= 12 and abs(b[1] - a[1]) >= 12:
                    corners = ((a[0], a[1]), (b[0], a[1]), (b[0], b[1]), (a[0], b[1]))
                    self._boundaries.append(
                        PhotoBoundary(corners=corners, confidence=1.0, user_confirmed=True)
                    )
                    self._selected = len(self._boundaries) - 1
                    self.boundaries_changed.emit(self.boundaries)
                    self.selection_changed.emit()
                else:
                    self.edit_rejected.emit("Draw a larger boundary inside the scan.")
        self.update()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Space:
            if not event.isAutoRepeat() and self._drag_corner is None and self._drag_start is None:
                self._space_pan = True
                if not self._panning:
                    self._restore_cursor()
            event.accept()
        elif event.key() == Qt.Key.Key_Escape:
            self._stop_pan()
            if self._drag_corner is not None and self._original_boundary is not None:
                index, _ = self._drag_corner
                self._boundaries[index] = self._original_boundary
                self.boundaries_changed.emit(self.boundaries)
            self._drag_corner = None
            self._original_boundary = None
            self._drag_start = None
            self._drag_current = None
            self._add_mode = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.update()
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Space:
            if not event.isAutoRepeat():
                self._space_pan = False
                if not self._panning:
                    self._restore_cursor()
            event.accept()
        else:
            super().keyReleaseEvent(event)

    def focusOutEvent(self, event) -> None:  # noqa: N802
        self._stop_pan()
        if self._drag_corner is not None and self._original_boundary is not None:
            self._boundaries[self._drag_corner[0]] = self._original_boundary
            self._drag_corner = None
            self._original_boundary = None
            self.boundaries_changed.emit(self.boundaries)
        self._drag_start = None
        self._drag_current = None
        super().focusOutEvent(event)
        self.update()

    def wheelEvent(self, event) -> None:  # noqa: N802
        if self._image is None:
            return
        pixel = event.pixelDelta()
        angle = event.angleDelta()
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = pixel.y() or angle.y()
            if delta:
                self.zoom_by(1.12 if delta > 0 else 1 / 1.12)
        elif event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            delta = (pixel.x() or pixel.y()) if not pixel.isNull() else (
                angle.x() or angle.y()
            ) / 3
            self._pan += QPointF(delta, 0)
            self.update()
        elif pixel.x() or angle.x():
            self._pan += QPointF(pixel.x() if pixel.x() else angle.x() / 3, 0)
            self.update()
        else:
            delta = pixel.y() or angle.y()
            if delta:
                self.zoom_by(1.12 if delta > 0 else 1 / 1.12)
        event.accept()

    def _hit_corner(self, point: QPointF) -> tuple[int, int] | None:
        for boundary_index, boundary in enumerate(self._boundaries):
            if boundary_index != self._selected:
                continue
            for corner_index, (x, y) in enumerate(boundary.corners):
                screen = self._image_to_widget(x, y)
                if math.hypot(screen.x() - point.x(), screen.y() - point.y()) <= 13:
                    return boundary_index, corner_index
        return None

    def _hit_boundary(self, point: QPointF) -> int | None:
        x, y = self._widget_to_image(point.x(), point.y())
        for index, boundary in enumerate(self._boundaries):
            polygon = np.asarray(boundary.corners, dtype=np.float32)
            if cv2.pointPolygonTest(polygon, (x, y), False) >= 0:
                return index
        return None

    def _target_rect(self) -> QRectF:
        if self._image is None:
            return QRectF()
        height, width = self._image.shape[:2]
        scale = self._scale * self._zoom
        left = (self.width() - width * scale) / 2 + self._pan.x()
        top = (self.height() - height * scale) / 2 + self._pan.y()
        return QRectF(left, top, width * scale, height * scale)

    def _image_to_widget(self, x: float, y: float) -> QPointF:
        target = self._target_rect()
        return QPointF(target.left() + x * self._scale * self._zoom, target.top() + y * self._scale * self._zoom)

    def _widget_to_image(self, x: float, y: float) -> tuple[float, float]:
        target = self._target_rect()
        scale = max(0.001, self._scale * self._zoom)
        return (x - target.left()) / scale, (y - target.top()) / scale
