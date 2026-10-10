from __future__ import annotations

import sys
import os
import tempfile
from pathlib import Path

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QMessageBox

from photo_splitter.main_window import MainWindow
from photo_splitter.preferences import Preferences
from photo_splitter import telemetry


def smoke_test(app: QApplication) -> int:
    import cv2
    import numpy as np
    from photo_splitter.detection import OpenCVPhotoDetector
    from photo_splitter.domain import DetectionSuccess, AmbiguousDetections
    from photo_splitter.imaging import export_photos
    from photo_splitter.main_window import ASSETS
    from photo_splitter.version import __version__

    image = np.full((350, 500, 3), 240, np.uint8)
    cv2.rectangle(image, (40, 40), (200, 280), (40, 100, 160), -1)
    outcome = OpenCVPhotoDetector().detect(image)
    assert isinstance(outcome, (DetectionSuccess, AmbiguousDetections)), outcome
    assert outcome.boundaries
    assert (ASSETS / "scan.svg").is_file()
    if getattr(sys, "frozen", False):
        bundle = Path(sys._MEIPASS)
        package_root = bundle.parent if sys.platform == "darwin" else bundle
        for name in ("LGPL-3.0.txt", "GPL-3.0.txt", "LGPL-2.1.txt", "Python-PSF.txt"):
            assert (bundle / "THIRD_PARTY_NOTICES" / "licenses" / name).is_file(), name
        import PySide6
        import shiboken6
        import importlib.util
        from PySide6 import QtCore, QtGui, QtWidgets

        for module in (PySide6, QtCore, QtGui, QtWidgets, shiboken6, cv2, np):
            location = Path(module.__file__).resolve()
            assert location.is_relative_to(package_root.resolve()), location
        sdk = importlib.util.find_spec("sentry_sdk")
        assert sdk is not None and Path(sdk.origin).resolve().is_relative_to(package_root.resolve())
    with tempfile.TemporaryDirectory() as directory:
        results = export_photos(
            image, tuple(item.confirmed() for item in outcome.boundaries),
            Path(directory), "smoke",
        )
        assert results and all(item.path.is_file() for item in results)
    window = MainWindow()
    window.show()
    app.processEvents()
    assert not window.grab().isNull()
    window.close()
    print(f"SplitScan {__version__}: Qt, assets, detection and export smoke test passed")
    return 0


def main() -> int:
    from photo_splitter.version import __version__

    if "--version" in sys.argv:
        print(f"SplitScan {__version__}")
        return 0
    testing = "--smoke-test" in sys.argv
    if testing:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication(sys.argv)
    app.setApplicationName("SplitScan")
    app.setOrganizationName("Keepsake")
    app.setFont(QFont("Inter", 10))
    if testing:
        return smoke_test(app)
    preferences = Preferences()
    try:
        telemetry.configure(preferences.crash_reporting())
    except (ImportError, ValueError, OSError) as error:
        QMessageBox.warning(
            None, "Crash reporting unavailable",
            f"Crash reporting could not start and remains disabled:\n{error}",
        )
        telemetry.configure(False)
    previous_hook = sys.excepthook
    window = None

    def report_exception(kind, exception, traceback):
        telemetry.capture_exception(exception)
        previous_hook(kind, exception, traceback)
        QMessageBox.critical(
            window, "Unexpected application error",
            f"{kind.__name__}: {exception}\nThe operation could not be completed.",
        )

    sys.excepthook = report_exception
    window = MainWindow()
    window.show()
    try:
        return app.exec()
    finally:
        sys.excepthook = previous_hook
        telemetry.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
