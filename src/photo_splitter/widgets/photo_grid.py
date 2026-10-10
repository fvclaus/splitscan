from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QMenu,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from photo_splitter.domain import PhotoBoundary


@dataclass(frozen=True)
class PhotoPreview:
    boundary: PhotoBoundary
    thumbnail: np.ndarray
    width: int
    height: int


class PhotoGrid(QScrollArea):
    selection_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self._content = QWidget()
        self._layout = QGridLayout(self._content)
        self._layout.setContentsMargins(8, 8, 8, 8)
        self._layout.setHorizontalSpacing(12)
        self._layout.setVerticalSpacing(12)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.setWidget(self._content)
        self._items: list[PhotoPreview] = []
        self._checks: list[QCheckBox] = []
        self._list_mode = False
        self._empty = QLabel("Extract photos to preview them here")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setStyleSheet("color: #69716c; padding: 48px;")
        self._layout.addWidget(self._empty, 0, 0)

    @property
    def items(self) -> tuple[PhotoPreview, ...]:
        return tuple(self._items)

    def set_previews(self, items: tuple[PhotoPreview, ...]) -> None:
        self._items = list(items)
        self._checks = []
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()
        if not items:
            self._empty = QLabel("Extract photos to preview them here")
            self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._empty.setStyleSheet("color: #69716c; padding: 48px;")
            self._layout.addWidget(self._empty, 0, 0)
            return
        for index, item in enumerate(items):
            self._add_card(index, item)

    def set_list_mode(self, enabled: bool) -> None:
        if self._list_mode != enabled:
            selected = self.selected_indices()
            self._list_mode = enabled
            self.set_previews(tuple(self._items))
            for index, checkbox in enumerate(self._checks):
                checkbox.setChecked(index in selected)

    def selected_indices(self) -> tuple[int, ...]:
        return tuple(index for index, checkbox in enumerate(self._checks) if checkbox.isChecked())

    def set_all_selected(self, selected: bool) -> None:
        for checkbox in self._checks:
            checkbox.setChecked(selected)

    def _add_card(self, index: int, item: PhotoPreview) -> None:
        card = QWidget()
        card.setObjectName("photoCard")
        card.setFixedHeight(215)
        card.setStyleSheet(
            "QWidget#photoCard { background: white; border: 1px solid #dde2dd; border-radius: 8px; }"
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        image_label = QLabel()
        image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image_label.setMinimumSize(140, 92)
        image_label.setMaximumHeight(154)
        rgb = cv2.cvtColor(item.thumbnail, cv2.COLOR_BGR2RGB)
        height, width = rgb.shape[:2]
        image = QImage(rgb.data, width, height, rgb.strides[0], QImage.Format.Format_RGB888).copy()
        image_label.setPixmap(QPixmap.fromImage(image).scaled(
            260, 154, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        ))
        checkbox = QCheckBox(f"Photo {index + 1:02d}")
        checkbox.setChecked(item.boundary.selected)
        checkbox.toggled.connect(lambda checked: self.selection_changed.emit())
        more = QToolButton()
        more.setIcon(QIcon(str(Path(__file__).parents[1] / "assets" / "ellipsis.svg")))
        more.setToolTip("Photo selection actions")
        menu = QMenu(more)
        menu.addAction("Include photo", lambda: checkbox.setChecked(True))
        menu.addAction("Exclude photo", lambda: checkbox.setChecked(False))
        more.setMenu(menu)
        more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        selection_row = QHBoxLayout()
        selection_row.addWidget(checkbox)
        selection_row.addStretch()
        selection_row.addWidget(more)
        dimensions = QLabel(f"{item.width:,} × {item.height:,} px")
        dimensions.setStyleSheet("color: #69716c; font-size: 11px; border: 0;")
        layout.addWidget(image_label)
        layout.addLayout(selection_row)
        layout.addWidget(dimensions)
        self._checks.append(checkbox)
        columns = 1 if self._list_mode else 2
        self._layout.addWidget(card, index // columns, index % columns)
