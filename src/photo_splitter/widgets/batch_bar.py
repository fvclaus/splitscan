from __future__ import annotations

from PySide6.QtCore import QEvent, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QHelpEvent, QPainter, QPen
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QToolTip, QWidget

from photo_splitter.batch import Batch, ScanOutcome

GREEN = "#286b58"
MUTED = "#69716c"
LINE = "#dde2dd"
OUTCOME_COLORS = {
    ScanOutcome.EXPORTED: QColor(GREEN),
    ScanOutcome.SKIPPED: QColor("#b3bab5"),
    ScanOutcome.FAILED: QColor("#c46a2f"),
}
NARROW_WIDTH = 1052
SEGMENT_GAP = 4.0


class SegmentStrip(QWidget):
    """One rounded segment per scan, coloured by what happened to it."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._batch: Batch | None = None
        self.setFixedHeight(12)
        self.setMinimumWidth(120)
        self.setMouseTracking(True)

    def sizeHint(self) -> QSize:
        return QSize(360, 12)

    def set_batch(self, batch: Batch | None) -> None:
        self._batch = batch
        self.update()

    def _segment_rect(self, index: int) -> QRectF:
        assert self._batch is not None
        width = (self.width() - SEGMENT_GAP * (self._batch.total - 1)) / self._batch.total
        left = index * (width + SEGMENT_GAP)
        return QRectF(left, 1, max(width, 1.0), self.height() - 2)

    def segment_label(self, index: int) -> str:
        assert self._batch is not None
        name = self._batch.paths[index].name
        outcome = self._batch.outcome_of(index)
        if outcome is ScanOutcome.EXPORTED:
            status = "exported"
        elif outcome is ScanOutcome.SKIPPED:
            status = "skipped"
        elif outcome is ScanOutcome.FAILED:
            status = "could not be read"
        elif index == self._batch.index:
            status = "reviewing"
        elif index == self._batch.index + 1:
            status = "up next"
        else:
            status = "waiting"
        return f"{name} · {status}"

    def _index_at(self, x: float) -> int | None:
        if self._batch is None:
            return None
        for index in range(self._batch.total):
            rect = self._segment_rect(index)
            if rect.left() - SEGMENT_GAP / 2 <= x <= rect.right() + SEGMENT_GAP / 2:
                return index
        return None

    def event(self, event: QEvent) -> bool:
        if event.type() == QEvent.Type.ToolTip and isinstance(event, QHelpEvent):
            index = self._index_at(event.pos().x())
            if index is None:
                QToolTip.hideText()
            else:
                QToolTip.showText(event.globalPos(), self.segment_label(index), self)
            return True
        return super().event(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        if self._batch is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for index in range(self._batch.total):
            rect = self._segment_rect(index)
            radius = rect.height() / 2
            outcome = self._batch.outcome_of(index)
            if outcome is not None:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(OUTCOME_COLORS[outcome])
            elif index == self._batch.index:
                painter.setPen(QPen(QColor(GREEN), 2))
                painter.setBrush(QColor("#eaf3ee"))
                rect = rect.adjusted(1, 1, -1, -1)
            else:
                painter.setPen(QPen(QColor("#c9cfca"), 1))
                painter.setBrush(QColor("#e3e7e3"))
            painter.drawRoundedRect(rect, radius, radius)


class BatchBar(QFrame):
    """Shows which scan of a batch is open and what is left, hidden outside batches."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("batchBar")
        self.setStyleSheet(
            f"QFrame#batchBar {{ background:white; border:1px solid {LINE};"
            " border-radius:10px; margin:12px 0; }"
        )
        self.setAccessibleName("Batch progress")
        self._layout = QGridLayout(self)
        self._layout.setContentsMargins(18, 10, 18, 10)
        self._layout.setHorizontalSpacing(24)
        self._layout.setVerticalSpacing(8)
        self._caption = QLabel()
        self._caption.setStyleSheet(f"color:{MUTED}; font-size:11px; border:0;")
        self._title = QLabel()
        self._title.setStyleSheet("font-size:15px; font-weight:600; border:0;")
        self._title.setTextFormat(Qt.TextFormat.PlainText)
        title_column = QWidget()
        title_layout = QGridLayout(title_column)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(3)
        title_layout.addWidget(self._caption, 0, 0)
        title_layout.addWidget(self._title, 1, 0)
        self._title_column = title_column
        self._strip = SegmentStrip()
        self._counts = QLabel()
        self._counts.setStyleSheet("font-size:12px; color:#4d5550; border:0;")
        self._layout.addWidget(title_column, 0, 0)
        self._layout.addWidget(self._strip, 0, 1)
        self._layout.setColumnStretch(1, 1)
        self._narrow: bool | None = None
        self._place_counts(False)
        self.hide()

    @property
    def strip(self) -> SegmentStrip:
        return self._strip

    @property
    def title_text(self) -> str:
        return self._title.text()

    @property
    def counts_text(self) -> str:
        return self._counts.text()

    @property
    def is_narrow(self) -> bool:
        return bool(self._narrow)

    def set_batch(self, batch: Batch | None) -> None:
        self._strip.set_batch(batch)
        if batch is None:
            self.hide()
            return
        self._caption.setText(f"Batch · {batch.total} scans")
        self._title.setText(f"Scan {batch.index + 1} of {batch.total} · {batch.current.name}")
        self._counts.setText(self._summary(batch))
        self.show()

    @staticmethod
    def _summary(batch: Batch) -> str:
        parts = []
        for outcome, text in (
            (ScanOutcome.EXPORTED, "exported"),
            (ScanOutcome.SKIPPED, "skipped"),
            (ScanOutcome.FAILED, "couldn't be read"),
        ):
            count = batch.count(outcome)
            if count:
                parts.append(f"{count} {text}")
        parts.append(f"{batch.remaining} remaining")
        return " · ".join(parts)

    def _place_counts(self, narrow: bool) -> None:
        if narrow == self._narrow:
            return
        self._narrow = narrow
        self._layout.removeWidget(self._counts)
        if narrow:
            self._layout.addWidget(self._counts, 1, 0, 1, 2)
        else:
            self._layout.addWidget(self._counts, 0, 2)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._place_counts(self.width() < NARROW_WIDTH)
