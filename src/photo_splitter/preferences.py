from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings


class Preferences:
    def __init__(self) -> None:
        self._settings = QSettings(
            QSettings.defaultFormat(), QSettings.Scope.UserScope, "Keepsake", "PhotoSplitter"
        )

    def output_directory(self) -> Path | None:
        value = self._settings.value("output_directory", "", type=str)
        if not value:
            return None
        path = Path(value).expanduser()
        return path if path.is_dir() else None

    def set_output_directory(self, path: Path) -> None:
        if not path.is_dir():
            raise NotADirectoryError(f"Output folder does not exist: {path}")
        self._settings.setValue("output_directory", str(path.resolve()))
        self._settings.sync()
        if self._settings.status() != QSettings.Status.NoError:
            raise OSError("Could not persist the output folder in application settings.")

    def detection_threshold(self) -> int:
        value = self._settings.value("detection_threshold", 18, type=int)
        return min(80, max(1, value))

    def set_detection_threshold(self, value: int) -> None:
        if not 1 <= value <= 80:
            raise ValueError("Detection threshold must be between 1 and 80.")
        self._settings.setValue("detection_threshold", value)

    def crash_reporting(self) -> bool:
        return self._settings.value("crash_reporting", False, type=bool)

    def set_crash_reporting(self, enabled: bool) -> None:
        previous = self.crash_reporting()
        self._settings.setValue("crash_reporting", enabled)
        self._settings.sync()
        if self._settings.status() != QSettings.Status.NoError:
            self._settings.setValue("crash_reporting", previous)
            raise OSError("Could not save crash-reporting preference.")
