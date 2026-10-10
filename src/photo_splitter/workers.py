from __future__ import annotations

from collections.abc import Callable
import logging
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Signal

from photo_splitter.domain import OperationCancelled
from photo_splitter.telemetry import capture_exception

class WorkerSignals(QObject):
    finished = Signal(int, object)
    failed = Signal(int, str)
    cancelled = Signal(int)


class Worker(QRunnable):
    def __init__(
        self, token: int, operation: Callable[..., Any], *args: Any, **kwargs: Any
    ) -> None:
        super().__init__()
        self.token = token
        self.operation = operation
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            self.signals.finished.emit(self.token, self.operation(*self.args, **self.kwargs))
        except OperationCancelled:
            self.signals.cancelled.emit(self.token)
        except Exception as exc:
            logging.exception("Photo processing failed")
            capture_exception(exc)
            self.signals.failed.emit(self.token, str(exc) or type(exc).__name__)
