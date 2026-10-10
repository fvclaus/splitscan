import sys
from types import SimpleNamespace

from photo_splitter import telemetry
from photo_splitter.preferences import Preferences
from photo_splitter.workers import Worker


def test_sanitization_removes_private_content():
    event = {
        "event_id": "123",
        "user": {"email": "private@example.com"},
        "request": {"url": "secret"},
        "extra": {"scan": "pixels"},
        "breadcrumbs": [{"message": "/home/private/photo.jpg"}],
        "exception": {"values": [{
            "type": "ValueError",
            "value": "/home/private/photo.jpg",
            "stacktrace": {"frames": [
                {"module": "photo_splitter.imaging", "filename": "/home/private/app.py",
                 "lineno": 12, "vars": {"scan": "pixels"}, "context_line": "secret"},
                {"module": "user_plugin", "filename": "/home/private/photo.jpg"},
            ]},
        }]},
    }
    sanitized = telemetry.sanitize_event(event, {})
    assert not any(key in sanitized for key in ("user", "extra", "request", "breadcrumbs"))
    assert "private" not in str(sanitized)
    assert "pixels" not in str(sanitized)
    frame = sanitized["exception"]["values"][0]["stacktrace"]["frames"][0]
    assert frame == {"module": "photo_splitter.imaging", "filename": "photo_splitter/imaging.py",
                     "lineno": 12, "in_app": True}


def test_opt_in_capture_and_disable_use_fake_transport(monkeypatch):
    calls = []

    class Client:
        def __init__(self, **options):
            self.options = options
            calls.append(options)

        def capture_event(self, event, hint, scope):
            calls.append(type(hint["exception"]))

        def close(self, timeout):
            calls.append(("close", timeout))

        def flush(self, timeout):
            calls.append(("flush", timeout))

    class Scope:
        def set_client(self, client):
            self.client = client


    monkeypatch.setitem(sys.modules, "sentry_sdk", SimpleNamespace(Client=Client, Scope=Scope))
    monkeypatch.setitem(
        sys.modules, "sentry_sdk.utils",
        SimpleNamespace(event_from_exception=lambda exception, client_options: (
            {}, {"exception": exception}
        )),
    )
    telemetry.configure(False)
    telemetry.capture_exception(ValueError("private"))
    assert not calls
    telemetry.configure(True)
    assert calls[0]["send_default_pii"] is False
    assert calls[0]["include_local_variables"] is False
    assert calls[0]["default_integrations"] is False
    telemetry.capture_exception(ValueError("private"))
    assert calls[-1] is ValueError
    telemetry.configure(False)
    count = len(calls)
    telemetry.capture_exception(ValueError("private"))
    assert len(calls) == count


def test_caught_worker_error_is_reported_once(app, monkeypatch):
    reports = []
    monkeypatch.setattr("photo_splitter.workers.capture_exception", reports.append)
    error = ValueError("private")

    def fail():
        raise error

    Worker(1, fail).run()
    assert reports == [error]


def test_consent_is_off_by_default_and_persisted(app):
    preferences = Preferences()
    assert not preferences.crash_reporting()
    preferences.set_crash_reporting(True)
    assert Preferences().crash_reporting()
    preferences.set_crash_reporting(False)


def test_shutdown_flush_is_bounded(monkeypatch):
    calls = []

    class Client:
        def flush(self, timeout):
            calls.append(("flush", timeout))

        def close(self, timeout):
            calls.append(("close", timeout))

    monkeypatch.setattr(telemetry, "_client", Client())
    monkeypatch.setattr(telemetry, "_scope", object())
    telemetry.shutdown()
    assert calls == [("flush", 1), ("close", 0)]
    assert telemetry._client is None and telemetry._scope is None


def test_real_sdk_transport_receives_only_sanitized_errors(monkeypatch):
    import sentry_sdk
    from sentry_sdk.transport import Transport

    envelopes = []

    class RecordingTransport(Transport):
        def capture_envelope(self, envelope):
            envelopes.append(envelope)

    original_client = sentry_sdk.Client

    def offline_client(**options):
        options["transport"] = RecordingTransport
        return original_client(**options)

    monkeypatch.setattr(sentry_sdk, "Client", offline_client)
    try:
        telemetry.configure(True)
        try:
            raise ValueError("/home/private/scans/secret-photo.jpg")
        except ValueError as error:
            telemetry.capture_exception(error)
        assert len(envelopes) == 1
        serialized = envelopes[0].serialize()
        assert b"private" not in serialized
        assert b"secret-photo" not in serialized
        assert b"ValueError" in serialized
        telemetry.configure(False)
        telemetry.capture_exception(ValueError("private"))
        assert len(envelopes) == 1
    finally:
        telemetry.configure(False)
