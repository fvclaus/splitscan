import pytest
from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QMessageBox

from photo_splitter import app as application, telemetry
from photo_splitter.main_window import MainWindow
from photo_splitter.preferences import Preferences
from photo_splitter.privacy_dialog import PrivacyDialog


@pytest.fixture
def preferences(app, monkeypatch, tmp_path):
    original_init = Preferences.__init__

    def isolated_init(self):
        original_init(self)
        self._settings = QSettings(str(tmp_path / "privacy.ini"), QSettings.Format.IniFormat)

    monkeypatch.setattr(Preferences, "__init__", isolated_init)
    return Preferences()


@pytest.mark.parametrize("usage,crashes", [(False, False), (True, False), (False, True), (True, True)])
def test_choices_default_off_and_persist(preferences, usage, crashes):
    assert not preferences.privacy_choices_saved()
    assert not preferences.usage_statistics()
    assert not preferences.crash_reporting()
    preferences.set_privacy_choices(usage, crashes)
    restarted = Preferences()
    assert restarted.privacy_choices_saved()
    assert restarted.usage_statistics() == usage
    assert restarted.crash_reporting() == crashes


def test_failed_consent_write_restores_values_and_prompt_flag(preferences, monkeypatch):
    monkeypatch.setattr(preferences._settings, "sync", lambda: None)
    monkeypatch.setattr(
        preferences._settings, "status", lambda: QSettings.Status.AccessError
    )
    with pytest.raises(OSError, match="Could not save privacy choices"):
        preferences.set_privacy_choices(True, True)
    assert not preferences.privacy_choices_saved()
    assert not preferences.usage_statistics()
    assert not preferences.crash_reporting()


def test_onboarding_unchecked_close_and_saved_settings(preferences, monkeypatch):
    calls = []
    monkeypatch.setattr(telemetry, "configure", lambda *args: calls.append(args))
    preferences.set_crash_reporting(True)
    dialog = PrivacyDialog(preferences)
    assert not dialog.crash_reporting.isChecked()
    assert not dialog.usage_statistics.isChecked()
    dialog.reject()
    assert not preferences.privacy_choices_saved()
    assert not calls
    dialog = PrivacyDialog(preferences)
    dialog.usage_statistics.setChecked(True)
    dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Save).click()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert calls == [(False,), (False, True)]
    settings = PrivacyDialog(Preferences())
    assert settings.windowTitle() == "Settings"
    assert settings.usage_statistics.isChecked()
    assert not settings.crash_reporting.isChecked()


@pytest.mark.parametrize("failure", ["persist", "configure"])
def test_dialog_failure_visible_and_reporting_inactive(preferences, monkeypatch, failure):
    calls, warnings = [], []

    def configure(*args):
        calls.append(args)
        if args == (True, True) and failure == "configure":
            raise ValueError("invalid configuration")

    monkeypatch.setattr(telemetry, "configure", configure)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))
    if failure == "persist":
        def fail(*args):
            raise OSError("settings not writable")
        monkeypatch.setattr(preferences, "set_privacy_choices", fail)
    dialog = PrivacyDialog(preferences)
    dialog.usage_statistics.setChecked(True)
    dialog.crash_reporting.setChecked(True)
    dialog._save()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert warnings and "inactive" in warnings[0][-1]
    assert calls[-1] == (False,)
    assert dialog.usage_statistics.isChecked() and dialog.crash_reporting.isChecked()
    if failure == "persist":
        assert not preferences.privacy_choices_saved()


def test_settings_button_beside_about_opens_shared_dialog(preferences, monkeypatch):
    dialogs = []
    monkeypatch.setattr(PrivacyDialog, "exec", lambda self: dialogs.append(self))
    window = MainWindow()
    window.settings_button.click()
    assert len(dialogs) == 1 and dialogs[0].parent() is window
    header = window.settings_button.parentWidget().layout()
    assert header.indexOf(window.settings_button) + 1 == header.indexOf(window.about_button)
    assert not hasattr(window, "crash_reporting")
    window.close()


@pytest.mark.parametrize("saved,close", [(False, False), (False, True), (True, False)])
def test_normal_startup_resolves_consent_before_app_opened(preferences, monkeypatch, app, saved, close):
    calls = []
    if saved:
        preferences.set_privacy_choices(True, False)
    monkeypatch.setattr(application, "QApplication", lambda argv: app)
    monkeypatch.setattr(telemetry, "configure", lambda *args: calls.append(("configure", args)))
    monkeypatch.setattr(telemetry, "capture_usage", lambda name: calls.append(("event", name)))
    monkeypatch.setattr(telemetry, "shutdown", lambda: calls.append(("shutdown",)))
    monkeypatch.setattr(application.sys, "argv", ["photo-splitter"])

    def choose(dialog):
        assert not app.windowIcon().isNull()
        calls.append(("prompt",))
        if close:
            dialog.reject()
        else:
            dialog.usage_statistics.setChecked(True)
            dialog._save()
        return dialog.result()

    monkeypatch.setattr(PrivacyDialog, "exec", choose)
    QTimer.singleShot(0, app.quit)
    assert application.main() == 0
    assert calls[0] == ("configure", (False,))
    assert calls[-2:] == [("event", "app_opened"), ("shutdown",)]
    assert ("prompt",) in calls if not saved else ("prompt",) not in calls
    if close:
        assert not preferences.privacy_choices_saved()
        assert not any(item == ("configure", (False, True)) for item in calls)
    else:
        assert preferences.privacy_choices_saved()
        assert ("configure", (False, True)) in calls
    for widget in app.topLevelWidgets():
        if isinstance(widget, MainWindow):
            widget.close()


@pytest.mark.parametrize("argument", ["--version", "--smoke-test"])
def test_noninteractive_modes_bypass_consent_and_telemetry(preferences, monkeypatch, app, argument):
    def unexpected(*args):
        raise AssertionError("Noninteractive modes must not prompt or configure telemetry")
    monkeypatch.setattr(application.sys, "argv", ["photo-splitter", argument])
    monkeypatch.setattr(application, "QApplication", lambda argv: app)
    monkeypatch.setattr(PrivacyDialog, "exec", unexpected)
    monkeypatch.setattr(telemetry, "configure", unexpected)
    monkeypatch.setattr(telemetry, "capture_usage", unexpected)
    monkeypatch.setattr(application, "smoke_test", lambda app: 0)
    assert application.main() == 0


@pytest.mark.parametrize("save", [False, True])
def test_real_modal_onboarding_decline_or_close(preferences, monkeypatch, app, save):
    calls = []
    monkeypatch.setattr(telemetry, "configure", lambda *args: calls.append(args))
    dialog = PrivacyDialog(preferences)
    QTimer.singleShot(0, dialog._save if save else dialog.reject)
    assert dialog.exec() == (
        QDialog.DialogCode.Accepted if save else QDialog.DialogCode.Rejected
    )
    assert preferences.privacy_choices_saved() == save
    assert not preferences.usage_statistics() and not preferences.crash_reporting()
    assert calls == ([(False,), (False, False)] if save else [])


def test_saved_consent_startup_configuration_failure_is_visible(preferences, monkeypatch, app):
    calls, warnings = [], []
    preferences.set_privacy_choices(True, True)

    def configure(*args):
        calls.append(args)
        if args == (True, True):
            raise OSError("cannot start reporting")

    monkeypatch.setattr(application, "QApplication", lambda argv: app)
    monkeypatch.setattr(application.sys, "argv", ["photo-splitter"])
    monkeypatch.setattr(telemetry, "configure", configure)
    monkeypatch.setattr(telemetry, "capture_usage", lambda *args: None)
    monkeypatch.setattr(telemetry, "shutdown", lambda: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))
    QTimer.singleShot(0, app.quit)
    assert application.main() == 0
    assert calls == [(False,), (True, True), (False,)]
    assert warnings and "remains disabled" in warnings[0][-1]
    for widget in app.topLevelWidgets():
        if isinstance(widget, MainWindow):
            widget.close()
