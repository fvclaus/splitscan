from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QLabel, QMessageBox, QVBoxLayout, QWidget,
)

from photo_splitter import telemetry
from photo_splitter.preferences import Preferences


class PrivacyDialog(QDialog):
    def __init__(self, preferences: Preferences, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._preferences = preferences
        self.setWindowTitle("Settings" if preferences.privacy_choices_saved() else "Your privacy choices")
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        intro_text = (
            "Help improve SplitScan. Both choices are optional and independent.\n"
            "All photo processing stays on your device. Change these choices in Settings."
        )
        if not preferences.privacy_choices_saved():
            intro_text += (
                "\nClosing without saving keeps reporting inactive and asks again next launch."
            )
        intro = QLabel(intro_text)
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.usage_statistics = QCheckBox("Send usage statistics (optional)")
        self.crash_reporting = QCheckBox("Send sanitized crash reports (optional)")
        if preferences.privacy_choices_saved():
            self.usage_statistics.setChecked(preferences.usage_statistics())
            self.crash_reporting.setChecked(preferences.crash_reporting())
        layout.addWidget(self.usage_statistics)
        usage = QLabel(
            "Sentry Logs receives app opens, scan loads, committed border corrections, and successful "
            "photo extractions and saves, with photo counts where relevant, app version and OS."
        )
        usage.setWordWrap(True)
        layout.addWidget(usage)
        layout.addWidget(self.crash_reporting)
        crashes = QLabel(
            "Sentry receives exception types, application stack locations, app version and OS. "
            "Exception messages and sensitive breadcrumbs are removed."
        )
        crashes.setWordWrap(True)
        layout.addWidget(crashes)
        privacy = QLabel(
            "Neither option sends photos, image data, filenames, user paths or user/device IDs. "
            "Network services can observe your source IP. Disabling a choice stops future reports; "
            "requests already in flight cannot be recalled."
        )
        privacy.setWordWrap(True)
        layout.addWidget(privacy)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Save choices")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save(self) -> None:
        usage = self.usage_statistics.isChecked()
        crashes = self.crash_reporting.isChecked()
        try:
            # Stop pending reports before persisting or applying a consent change.
            telemetry.configure(False)
            self._preferences.set_privacy_choices(usage, crashes)
            telemetry.configure(crashes, usage)
        except (OSError, ImportError, ValueError) as error:
            telemetry.configure(False)
            QMessageBox.warning(
                self, "Could not apply privacy choices",
                f"Reporting remains inactive for this launch. Please retry saving your choices.\n{error}",
            )
            return
        self.accept()
