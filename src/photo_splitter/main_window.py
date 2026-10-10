from __future__ import annotations

from pathlib import Path
from threading import Event

import cv2
import numpy as np
from PySide6.QtCore import Qt, QThreadPool, QTimer
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from photo_splitter.detection import OpenCVPhotoDetector
from photo_splitter.domain import (
    AmbiguousDetections,
    DetectionFailure,
    DetectionOutcome,
    DetectionSuccess,
    NoDetections,
    OperationCancelled,
    PhotoBoundary,
)
from photo_splitter.imaging import (
    ExportedPhoto,
    extract_photo,
    export_photos,
    read_scan,
)
from photo_splitter.preferences import Preferences
from photo_splitter.widgets.photo_grid import PhotoGrid, PhotoPreview
from photo_splitter.widgets.scan_view import ScanView
from photo_splitter.workers import Worker


GREEN = "#286b58"
INK = "#202923"
MUTED = "#69716c"
LINE = "#dde2dd"
SURFACE = "#ffffff"
CANVAS = "#f5f6f4"
ASSETS = Path(__file__).parent / "assets"


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Keepsake — Photo Splitter")
        self.setMinimumSize(800, 700)
        self.resize(1440, 900)
        self.setStyleSheet(
            f"QMainWindow, QWidget#workspace {{ background: {CANVAS}; color: {INK}; }}"
            f"QLabel {{ color: {INK}; }}"
            f"QPushButton {{ color: {INK}; background: white; border: 1px solid {LINE};"
            " border-radius: 7px; padding: 8px 12px; }"
            f"QPushButton:hover {{ border-color: {GREEN}; }}"
            f"QPushButton:disabled {{ color: #a6aca7; background: #f3f4f3; }}"
            f"QCheckBox {{ spacing: 7px; }}"
            "QCheckBox::indicator { width:14px; height:14px; border:1px solid #abb5ae; border-radius:3px; }"
            f"QCheckBox::indicator:checked {{ background:{GREEN}; border-color:{GREEN};"
            f"image:url({ASSETS / 'check.svg'}); }}"
        )
        self._preferences = Preferences()
        self._detector = OpenCVPhotoDetector()
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(2)
        self._workers: dict[int, Worker] = {}
        self._token = 0
        self._active_token = 0
        self._scan_path: Path | None = None
        self._scan: np.ndarray | None = None
        self._boundaries: tuple[PhotoBoundary, ...] = ()
        self._boundaries_modified = False
        self._updating_scan_view = False
        self._working = False
        self._cancel_event = Event()
        self._output_directory = self._preferences.output_directory()
        self._threshold_timer = QTimer(self)
        self._threshold_timer.setSingleShot(True)
        self._threshold_timer.timeout.connect(self._redetect)
        self._build_ui()
        self._update_controls()

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("workspace")
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(24, 0, 24, 0)
        root_layout.setSpacing(0)

        header = QFrame()
        header.setFixedHeight(64)
        header.setObjectName("header")
        header.setStyleSheet(f"QFrame#header {{ background: {SURFACE}; border-bottom: 1px solid {LINE}; }}")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        brand_mark = QLabel()
        brand_mark.setPixmap(QIcon(str(ASSETS / "scan-line.svg")).pixmap(20, 20))
        brand_mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand_mark.setFixedSize(30, 30)
        brand_mark.setStyleSheet(f"background:{GREEN}; color:white; border-radius:7px; font-size:18px;")
        brand = QLabel("Keepsake")
        brand.setFont(QFont("Inter", 15, QFont.Weight.Medium))
        header_layout.addWidget(brand_mark)
        header_layout.addWidget(brand)
        header_layout.addStretch()
        self.import_button = QPushButton("Import scan")
        self.import_button.setIcon(QIcon(str(ASSETS / "plus.svg")))
        self.import_button.clicked.connect(self._choose_scan)
        header_layout.addWidget(self.import_button)
        root_layout.addWidget(header)

        panes = QSplitter(Qt.Orientation.Horizontal)
        self.panes = panes
        panes.setChildrenCollapsible(False)
        panes.setMaximumHeight(684)
        panes.setHandleWidth(14)
        left = self._build_source_panel()
        right = self._build_results_panel()
        panes.addWidget(left)
        center = QWidget()
        center.setMaximumWidth(144)
        center.setMinimumWidth(130)
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.addStretch()
        self.extract_selection_label = QLabel("0 photos selected")
        self.extract_selection_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.extract_selection_label.setStyleSheet(f"color:{MUTED}; font-size:11px;")
        self.extract_button = QPushButton("Extract  →")
        self.extract_button.setStyleSheet(
            f"background:{GREEN}; color:white; border:0; font-weight:600; padding:12px 6px;"
        )
        self.extract_button.clicked.connect(self._start_preview)
        center_layout.addWidget(self.extract_selection_label)
        center_layout.addWidget(self.extract_button)
        self.cancel_button = QPushButton("Cancel processing")
        self.cancel_button.clicked.connect(self._cancel_processing)
        center_layout.addWidget(self.cancel_button)
        explanation = QLabel("Split into individual files.\nKeep the original intact.")
        explanation.setAlignment(Qt.AlignmentFlag.AlignCenter)
        explanation.setStyleSheet(f"color:{MUTED}; font-size:11px; padding:8px 0;")
        center_layout.addWidget(explanation)
        center_layout.addWidget(self.auto_straighten)
        center_layout.addWidget(self.trim_borders)
        center_layout.addStretch()
        self.center_panel = center
        panes.addWidget(center)
        panes.addWidget(right)
        panes.setStretchFactor(0, 1)
        panes.setStretchFactor(1, 0)
        panes.setStretchFactor(2, 1)
        panes.setSizes([600, 144, 616])
        root_layout.addWidget(panes, stretch=1)
        root_layout.addStretch()

        footer = QHBoxLayout()
        shield = QLabel()
        shield.setPixmap(QIcon(str(ASSETS / "shield.svg")).pixmap(16, 16))
        footer.addWidget(shield)
        self.privacy_label = QLabel("Your memories stay yours. All processing happens on this device.")
        self.privacy_label.setStyleSheet(f"color:{MUTED}; font-size:11px;")
        self.privacy_label.setWordWrap(True)
        footer.addWidget(self.privacy_label)
        footer.addStretch()
        tip = QLabel("Tip: drag a corner to fine-tune a photo boundary.")
        tip.setWordWrap(True)
        tip.setStyleSheet(f"color:{MUTED}; font-size:11px;")
        footer.addWidget(tip)
        root_layout.addLayout(footer)

        status_bar = QFrame()
        status_bar.setObjectName("status")
        status_bar.setStyleSheet(f"QFrame#status {{ background:white; border-top:1px solid {LINE}; }}")
        status_layout = QHBoxLayout(status_bar)
        status_layout.setContentsMargins(4, 5, 4, 5)
        self.status_label = QLabel("Ready  ·  Import a scan to begin")
        self.status_label.setStyleSheet(f"color:{MUTED}; font-size:11px;")
        self.footer_status = QLabel("Original scan preserved")
        self.footer_status.setStyleSheet(f"color:{MUTED}; font-size:11px;")
        status_layout.addWidget(self.status_label)
        status_layout.addStretch()
        status_layout.addWidget(self.footer_status)
        root_layout.addWidget(status_bar)
        self.setCentralWidget(root)
        self.statusBar().hide()

    def _build_source_panel(self) -> QWidget:
        panel = self._card()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        heading = QHBoxLayout()
        heading.setSpacing(10)
        heading.setContentsMargins(18, 15, 18, 12)
        icon = QLabel()
        icon.setPixmap(QIcon(str(ASSETS / "scan.svg")).pixmap(18, 18))
        heading.addWidget(icon)
        title = QLabel("Original scan")
        title.setFont(QFont("Inter", 11, QFont.Weight.DemiBold))
        heading.addWidget(title)
        heading.addStretch()
        self.detected_badge = QLabel("No scan loaded")
        self.detected_badge.setStyleSheet(f"color:{GREEN}; background:#eaf3ee; border-radius:10px; padding:5px 8px; font-size:10px;")
        heading.addWidget(self.detected_badge)
        layout.addLayout(heading)

        tools_frame = QFrame()
        tools_frame.setObjectName("sourceTools")
        tools_frame.setStyleSheet(f"QFrame#sourceTools {{ border-top:1px solid {LINE}; border-bottom:1px solid {LINE}; }}")
        tools = QHBoxLayout(tools_frame)
        tools.setContentsMargins(16, 8, 16, 8)
        self.select_all = QCheckBox("All selected")
        self.select_all.setChecked(True)
        self.select_all.toggled.connect(self._set_all_boundaries_selected)
        tools.addWidget(self.select_all)
        self.add_boundary_button = QPushButton("+  Add boundary")
        self.add_boundary_button.setFlat(True)
        self.add_boundary_button.clicked.connect(self._add_boundary)
        tools.addWidget(self.add_boundary_button)
        self.confirm_boundary_button = QPushButton("✓  Confirm boundary")
        self.confirm_boundary_button.clicked.connect(self._confirm_boundary)
        tools.addStretch()
        self.zoom_out_button = QPushButton()
        self.zoom_out_button.setIcon(QIcon(str(ASSETS / "minus.svg")))
        self.zoom_out_button.setToolTip("Zoom out")
        self.zoom_out_button.setFixedWidth(32)
        self.zoom_out_button.clicked.connect(lambda: self.scan_view.zoom_by(1 / 1.2))
        self.fit_button = QPushButton("Fit")
        self.fit_button.clicked.connect(lambda: self.scan_view.fit_scan())
        self.zoom_in_button = QPushButton()
        self.zoom_in_button.setIcon(QIcon(str(ASSETS / "zoom-plus.svg")))
        self.zoom_in_button.setToolTip("Zoom in")
        self.zoom_in_button.setFixedWidth(32)
        self.zoom_in_button.clicked.connect(lambda: self.scan_view.zoom_by(1.2))
        for button in (self.zoom_out_button, self.fit_button, self.zoom_in_button):
            tools.addWidget(button)
        layout.addWidget(tools_frame)

        self.scan_view = ScanView()
        self.scan_view.boundaries_changed.connect(self._boundaries_changed)
        self.scan_view.selection_changed.connect(self._selection_changed)
        self.scan_view.edit_rejected.connect(self._set_status)
        layout.addWidget(self.scan_view, stretch=1)

        source_footer = QHBoxLayout()
        source_footer.setContentsMargins(16, 10, 16, 10)
        self.source_info = QLabel("No scan loaded")
        self.source_info.setWordWrap(True)
        self.source_info.setStyleSheet(f"font-size:11px; color:{MUTED};")
        source_footer.addWidget(self.source_info, stretch=1)
        self.threshold_label = QLabel("Edge sensitivity")
        self.threshold_spin = QSpinBox()
        self.threshold_spin.setRange(1, 80)
        self.threshold_spin.setValue(self._preferences.detection_threshold())
        self.threshold_spin.setFixedWidth(64)
        self.threshold_spin.setToolTip("Lower values detect subtler photo borders")
        self.threshold_spin.valueChanged.connect(self._threshold_changed)
        self.re_detect_button = QPushButton("Re-detect")
        self.re_detect_button.setIcon(QIcon(str(ASSETS / "redetect.svg")))
        self.re_detect_button.clicked.connect(self._redetect)
        source_footer.addWidget(self.threshold_label)
        source_footer.addWidget(self.threshold_spin)
        source_footer.addWidget(self.re_detect_button)
        layout.addLayout(source_footer)
        layout.addWidget(self.confirm_boundary_button)
        self.source_panel = panel
        return panel

    def _build_results_panel(self) -> QWidget:
        panel = self._card()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        heading = QHBoxLayout()
        heading.setSpacing(10)
        heading.setContentsMargins(18, 15, 18, 12)
        icon = QLabel()
        icon.setPixmap(QIcon(str(ASSETS / "images.svg")).pixmap(18, 18))
        heading.addWidget(icon)
        title = QLabel("Extracted photos")
        title.setFont(QFont("Inter", 11, QFont.Weight.DemiBold))
        heading.addWidget(title)
        self.result_count = QLabel("0")
        self.result_count.setStyleSheet(f"color:{MUTED}; font-size:11px;")
        heading.addWidget(self.result_count)
        heading.addStretch()
        self.ready_badge = QLabel("Ready when you are")
        self.ready_badge.setStyleSheet(f"color:{GREEN}; background:#eaf3ee; border-radius:10px; padding:5px 8px; font-size:10px;")
        heading.addWidget(self.ready_badge)
        layout.addLayout(heading)

        controls = QFrame()
        controls.setObjectName("previewTools")
        controls.setStyleSheet(f"QFrame#previewTools {{ border-top:1px solid {LINE}; border-bottom:1px solid {LINE}; }}")
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(16, 6, 16, 6)
        self.preview_selection_label = QLabel("No photos selected")
        self.preview_selection_label.setStyleSheet(f"color:{MUTED}; font-size:11px;")
        controls_layout.addWidget(self.preview_selection_label)
        controls_layout.addStretch()
        controls_layout.addWidget(QLabel("Scan order"))
        self.view_mode = QComboBox()
        self.view_mode.addItem(QIcon(str(ASSETS / "grid.svg")), "Grid")
        self.view_mode.addItem(QIcon(str(ASSETS / "list.svg")), "List")
        self.view_mode.setFixedWidth(78)
        self.view_mode.currentIndexChanged.connect(
            lambda index: self.photo_grid.set_list_mode(index == 1)
        )
        controls_layout.addWidget(self.view_mode)
        layout.addWidget(controls)

        self.photo_grid = PhotoGrid()
        self.photo_grid.selection_changed.connect(self._update_selection_count)
        layout.addWidget(self.photo_grid, stretch=1)

        settings = QFrame()
        settings.setObjectName("exportSettings")
        settings.setStyleSheet(f"QFrame#exportSettings {{ border-top:1px solid {LINE}; }}")
        settings_layout = QVBoxLayout(settings)
        settings_layout.setContentsMargins(16, 10, 16, 12)
        settings_layout.setSpacing(8)
        self.auto_straighten = QCheckBox("Auto-straighten")
        self.auto_straighten.setChecked(True)
        self.trim_borders = QCheckBox("Trim borders")
        self.trim_borders.setChecked(True)
        self.auto_straighten.toggled.connect(self._invalidate_previews)
        self.trim_borders.toggled.connect(self._invalidate_previews)
        folder_row = QHBoxLayout()
        folder_text = QVBoxLayout()
        self.folder_title = QLabel("Save to")
        self.folder_title.setStyleSheet(f"font-size:10px; color:{MUTED};")
        self.folder_label = QLabel(self._display_output_folder())
        self.folder_label.setWordWrap(True)
        self.folder_label.setStyleSheet("font-size:11px;")
        self.folder_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        folder_text.addWidget(self.folder_title)
        folder_text.addWidget(self.folder_label)
        folder_row.addLayout(folder_text, stretch=1)
        self.folder_button = QPushButton("Choose folder")
        self.folder_button.clicked.connect(self._choose_output_folder)
        folder_row.addWidget(self.folder_button)
        settings_layout.addLayout(folder_row)
        export_row = QHBoxLayout()
        export_description = QLabel("JPEG  ·  Original pixel size  ·  Quality 100")
        export_description.setStyleSheet(f"font-size:10px; color:{MUTED};")
        export_row.addWidget(export_description)
        export_row.addStretch()
        self.export_button = QPushButton("Export selected")
        self.export_button.setIcon(QIcon(str(ASSETS / "download.svg")))
        self.export_button.clicked.connect(self._export_selected)
        export_row.addWidget(self.export_button)
        settings_layout.addLayout(export_row)
        layout.addWidget(settings)
        self.results_panel = panel
        return panel

    def _card(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("workspaceCard")
        frame.setStyleSheet(f"QFrame#workspaceCard {{ background:{SURFACE}; border:1px solid {LINE}; border-radius:10px; }}")
        frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        return frame

    def _choose_scan(self) -> None:
        if self._working:
            return
        if self._boundaries_modified and not self._confirm_discard():
            return
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Import scan",
            str(self._scan_path.parent) if self._scan_path else str(Path.home()),
            "Scans (*.jpg *.jpeg *.png *.tif *.tiff *.bmp);;All files (*)",
        )
        if filename:
            self._load_scan(Path(filename))

    def _load_scan(self, path: Path) -> None:
        threshold = self.threshold_spin.value()
        self._start_job(lambda: self._load_operation(path, threshold), "Loading scan…")

    def _load_operation(self, path: Path, threshold: int):
        image = read_scan(path)
        self._check_cancelled()
        return path, image, self._detector.detect(image, threshold)

    def _redetect(self) -> None:
        if self._scan_path is None or self._working:
            return
        if self._boundaries_modified and not self._confirm_discard():
            return
        self._preferences.set_detection_threshold(self.threshold_spin.value())
        path = self._scan_path
        threshold = self.threshold_spin.value()
        self._start_job(lambda: self._load_operation(path, threshold), "Detecting photo borders…")

    def _confirm_discard(self) -> bool:
        response = QMessageBox.question(
            self,
            "Replace edited boundaries?",
            "This will discard your current boundary and selection edits. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return response == QMessageBox.StandardButton.Yes

    def _confirm_boundary(self) -> None:
        self.scan_view.confirm_selected_boundary()

    def _threshold_changed(self, value: int) -> None:
        self._preferences.set_detection_threshold(value)
        if self._scan_path is not None:
            self._threshold_timer.start(350)

    def _add_boundary(self) -> None:
        self.scan_view.begin_add_boundary()
        self._set_status("Drag a rectangle around a photo to add a boundary")

    def _set_all_boundaries_selected(self, selected: bool) -> None:
        if not self._boundaries:
            return
        self._boundaries = tuple(
            PhotoBoundary(
                corners=item.corners,
                confidence=item.confidence,
                selected=selected,
                needs_review=item.needs_review,
                user_confirmed=item.user_confirmed,
                boundary_id=item.boundary_id,
            )
            for item in self._boundaries
        )
        self.scan_view.set_boundaries(self._boundaries)
        self._boundaries_modified = True
        self._invalidate_previews()
        self._update_detection_status()

    def _invalidate_previews(self) -> None:
        self.photo_grid.set_previews(())
        self.ready_badge.setText("Ready to extract")
        self._update_selection_count()

    def _boundaries_changed(self, boundaries: tuple[PhotoBoundary, ...]) -> None:
        self._boundaries = boundaries
        if not self._updating_scan_view:
            self._boundaries_modified = True
            self._invalidate_previews()
        self._update_detection_status()
        self._update_controls()

    def _selection_changed(self) -> None:
        selected = sum(boundary.selected for boundary in self._boundaries)
        self.select_all.blockSignals(True)
        self.select_all.setChecked(bool(self._boundaries) and selected == len(self._boundaries))
        self.select_all.blockSignals(False)
        self._update_detection_status()

    def _update_detection_status(self) -> None:
        count = len(self._boundaries)
        selected = sum(boundary.selected for boundary in self._boundaries)
        self.extract_selection_label.setText(f"{selected} photos selected")
        self.extract_button.setText(f"Extract {selected} photos")
        self.extract_button.setIcon(QIcon(str(ASSETS / "arrow.svg")))
        self.detected_badge.setText(f"{count} photo{'s' if count != 1 else ''} detected")
        self._update_controls()

    def _update_controls(self) -> None:
        has_scan = self._scan is not None
        self.import_button.setEnabled(not self._working)
        self.scan_view.setEnabled(not self._working)
        self.add_boundary_button.setEnabled(has_scan and not self._working)
        self.zoom_out_button.setEnabled(has_scan)
        self.zoom_in_button.setEnabled(has_scan)
        self.fit_button.setEnabled(has_scan)
        self.threshold_spin.setEnabled(has_scan and not self._working)
        self.re_detect_button.setEnabled(has_scan and not self._working)
        selected_index = self.scan_view.selected_boundary_index
        needs_confirmation = (
            0 <= selected_index < len(self._boundaries)
            and self._boundaries[selected_index].needs_review
            and not self._boundaries[selected_index].user_confirmed
        )
        self.confirm_boundary_button.setEnabled(needs_confirmation and not self._working)
        self.confirm_boundary_button.setVisible(needs_confirmation)
        self.select_all.setEnabled(bool(self._boundaries) and not self._working)
        self.folder_button.setEnabled(not self._working)
        self.auto_straighten.setEnabled(not self._working)
        self.trim_borders.setEnabled(not self._working)
        self.photo_grid.setEnabled(not self._working)
        self.cancel_button.setVisible(self._working)
        self.export_button.setEnabled(bool(self.photo_grid.selected_indices()) and not self._working)
        self.extract_button.setEnabled(
            has_scan and any(boundary.selected for boundary in self._boundaries) and not self._working
        )

    def _check_cancelled(self) -> None:
        if self._cancel_event.is_set():
            raise OperationCancelled("Processing cancelled.")

    def _cancel_processing(self) -> None:
        self._cancel_event.set()
        self.cancel_button.setEnabled(False)
        self._set_status("Cancelling after the current processing stage…")

    def _extract_selected(
        self,
        image: np.ndarray,
        boundaries: tuple[PhotoBoundary, ...],
        straighten: bool,
        trim: bool,
    ) -> tuple[PhotoPreview, ...]:
        selected = [boundary for boundary in boundaries if boundary.selected]
        previews: list[PhotoPreview] = []
        for boundary in selected:
            self._check_cancelled()
            crop = extract_photo(
                image,
                boundary,
                auto_straighten=straighten,
                trim_borders=trim,
            )
            factor = min(1.0, 420 / max(crop.shape[:2]))
            thumbnail = cv2.resize(
                crop,
                None,
                fx=factor,
                fy=factor,
                interpolation=cv2.INTER_AREA if factor < 1.0 else cv2.INTER_LINEAR,
            )
            previews.append(
                PhotoPreview(boundary, thumbnail, crop.shape[1], crop.shape[0])
            )
        return tuple(previews)

    def _start_preview(self) -> None:
        if self._working or self._scan is None:
            return
        if not self._boundaries or not any(item.selected for item in self._boundaries):
            self._set_status("Select at least one detected photo first")
            return
        image = self._scan
        boundaries = self._boundaries
        straighten = self.auto_straighten.isChecked()
        trim = self.trim_borders.isChecked()
        self._start_job(
            lambda: self._extract_selected(image, boundaries, straighten, trim),
            "Extracting preview photos…",
        )

    def _export_selected(self) -> None:
        if self._working or self._scan is None or self._scan_path is None:
            return
        selected_indices = self.photo_grid.selected_indices()
        if not selected_indices:
            self._set_status("Select at least one photo to export")
            return
        candidates = [item.boundary for item in self.photo_grid.items]
        selected = [candidates[index] for index in selected_indices]
        unconfirmed = [
            index + 1
            for index, boundary in enumerate(selected)
            if boundary.needs_review and not boundary.user_confirmed
        ]
        if unconfirmed:
            QMessageBox.warning(
                self,
                "Review photo boundaries",
                "Confirm or adjust the dashed photo boundaries on the scan before exporting.",
            )
            return
        if self._output_directory is None:
            self._choose_output_folder()
            if self._output_directory is None:
                return
        image = self._scan
        scan_stem = self._scan_path.stem
        output_directory = self._output_directory
        straighten = self.auto_straighten.isChecked()
        trim = self.trim_borders.isChecked()
        self._start_job(
            lambda: export_photos(
                image,
                selected,
                output_directory,
                scan_stem,
                auto_straighten=straighten,
                trim_borders=trim,
                cancelled=self._cancel_event.is_set,
            ),
            "Exporting JPEGs…",
        )

    def _choose_output_folder(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self,
            "Choose output folder",
            str(self._output_directory or Path.home()),
        )
        if not directory:
            return
        path = Path(directory)
        try:
            self._preferences.set_output_directory(path)
        except OSError as exc:
            QMessageBox.warning(self, "Could not save folder", str(exc))
            return
        self._output_directory = path
        self.folder_label.setText(self._display_output_folder())
        self._set_status("Output folder saved for future scans")

    def _display_output_folder(self) -> str:
        if self._output_directory is None:
            return "Choose a folder to save extracted photos"
        return str(self._output_directory)

    def _update_selection_count(self) -> None:
        count = len(self.photo_grid.selected_indices())
        total = len(self.photo_grid.items)
        self.preview_selection_label.setText(f"{count} of {total} selected")
        self.result_count.setText(str(total))
        self.export_button.setText(f"Export {count} photos")
        self._selection_changed()
        self._update_controls()

    def _start_job(self, operation, message: str) -> None:
        if self._working:
            return
        self._cancel_event.clear()
        self.cancel_button.setEnabled(True)
        self._token += 1
        token = self._token
        self._active_token = token
        worker = Worker(token, operation)
        worker.signals.finished.connect(self._job_finished)
        worker.signals.failed.connect(self._job_failed)
        worker.signals.cancelled.connect(self._job_cancelled)
        self._workers[token] = worker
        self._working = True
        self._set_status(message)
        self._update_controls()
        self._pool.start(worker)

    def _job_finished(self, token: int, result) -> None:
        self._workers.pop(token, None)
        if token != self._active_token:
            return
        if self._cancel_event.is_set() and not (
            isinstance(result, tuple) and result and isinstance(result[0], ExportedPhoto)
        ):
            self._job_cancelled(token)
            return
        self._working = False
        if isinstance(result, tuple) and len(result) == 3 and isinstance(result[0], Path):
            self._accept_scan(*result)
        elif isinstance(result, tuple) and (not result or isinstance(result[0], PhotoPreview)):
            self.photo_grid.set_previews(result)
            self.result_count.setText(str(len(result)))
            self.ready_badge.setText("Ready to export")
            self._update_selection_count()
            self._set_status(f"{len(result)} photo previews ready")
        elif isinstance(result, tuple) and (not result or isinstance(result[0], ExportedPhoto)):
            self._accept_export(result)
        else:
            self._set_status("Operation finished")
        self._update_controls()

    def _job_failed(self, token: int, reason: str) -> None:
        self._workers.pop(token, None)
        if token != self._active_token:
            return
        self._working = False
        self._set_status(f"Operation failed: {reason}")
        QMessageBox.warning(self, "Could not complete operation", reason)
        self._update_controls()

    def _job_cancelled(self, token: int) -> None:
        self._workers.pop(token, None)
        if token == self._active_token:
            self._working = False
            self._set_status("Processing cancelled. The original scan is unchanged.")
            self._update_controls()

    def _accept_scan(
        self, path: Path, image: np.ndarray, outcome: DetectionOutcome
    ) -> None:
        if isinstance(outcome, DetectionFailure):
            QMessageBox.warning(self, "Could not detect photos", outcome.reason)
            self._set_status(outcome.reason)
            return
        self._scan_path = path
        self._scan = image
        self._boundaries_modified = False
        self._updating_scan_view = True
        boundaries = outcome.boundaries if isinstance(outcome, (DetectionSuccess, AmbiguousDetections)) else ()
        self.scan_view.set_scan(image, boundaries)
        self._updating_scan_view = False
        self._boundaries = self.scan_view.boundaries
        self.photo_grid.set_previews(())
        self.result_count.setText("0")
        self.ready_badge.setText("Ready to extract")
        height, width = image.shape[:2]
        try:
            file_size = path.stat().st_size / (1024 * 1024)
            metadata = f"{width:,} × {height:,} px  ·  {file_size:.1f} MB"
        except OSError:
            metadata = f"{width:,} × {height:,} px"
        self.source_info.setText(f"{path.name}  ·  {metadata}")
        self.footer_status.setText(f"Original scan preserved  ·  {path.name}")
        if isinstance(outcome, NoDetections):
            self._set_status(outcome.reason)
            self.detected_badge.setText("No photos detected")
        elif isinstance(outcome, AmbiguousDetections):
            self._set_status(f"{outcome.reason} " + " ".join(outcome.diagnostics))
        else:
            self._set_status(f"{len(boundaries)} photo boundaries detected")
        self._update_selection_count()
        self._update_controls()

    def _accept_export(self, result: tuple[ExportedPhoto, ...]) -> None:
        files = ", ".join(item.path.name for item in result)
        self._set_status(f"Exported {len(result)} photo{'s' if len(result) != 1 else ''}: {files}")
        self.footer_status.setText(f"Saved to {self._output_directory}")
        QMessageBox.information(
            self,
            "Export complete",
            f"Saved {len(result)} JPEG photo{'s' if len(result) != 1 else ''} to:\n{self._output_directory}",
        )

    def _set_status(self, message: str) -> None:
        self.status_label.setText(message)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._active_token = -1
        self._cancel_event.set()
        self._threshold_timer.stop()
        self._pool.waitForDone()
        event.accept()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "panes"):
            orientation = Qt.Orientation.Vertical if self.width() < 1100 else Qt.Orientation.Horizontal
            if self.panes.orientation() != orientation:
                self.panes.setOrientation(orientation)
                self.center_panel.setMaximumWidth(16777215 if orientation == Qt.Orientation.Vertical else 144)
                self.panes.setMaximumHeight(16777215 if orientation == Qt.Orientation.Vertical else 684)
