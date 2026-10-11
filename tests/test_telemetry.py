import sys
from types import SimpleNamespace

import pytest

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
        sys.modules, "sentry_sdk.transport", SimpleNamespace(HttpTransport=object)
    )
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


def test_usage_is_not_sent_as_an_issue_event(monkeypatch):
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
        telemetry.configure(False, True)
        telemetry.capture_usage("app_opened")
        telemetry.shutdown()
        assert envelopes
        assert all(
            item.headers["type"] != "event"
            for envelope in envelopes for item in envelope.items
        ), "Usage statistics must not use Sentry's issue/error event ingestion"
    finally:
        telemetry.configure(False)


@pytest.mark.parametrize("usage,crashes", [(False, False), (True, False), (False, True), (True, True)])
def test_independent_consent_and_allowlisted_usage_envelopes(monkeypatch, usage, crashes):
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
    telemetry.configure(False)
    try:
        telemetry.configure(crashes, usage)
        telemetry.capture_usage("photos_extracted", 3)
        telemetry.capture_usage("photos_saved", 2)
        telemetry.capture_usage("app_opened")
        telemetry.capture_usage("scan_loaded")
        telemetry.capture_usage("boundary_corrected")
        telemetry.capture_usage("batch_started", 4)
        telemetry.capture_exception(ValueError("/home/private/secret-photo.jpg"))
        if telemetry._client is not None:
            telemetry._client.flush(timeout=1)
        items = [item for envelope in envelopes for item in envelope.items]
        usage_events = [
            log for item in items if item.headers["type"] == "log"
            for log in item.payload.json["items"]
        ]
        crash_events = [item.payload.json for item in items if item.headers["type"] == "event"]
        assert len(usage_events) == (6 if usage else 0)
        assert len(crash_events) == (1 if crashes else 0)
        assert all("exception" in event for event in crash_events)
        assert {item.headers["type"] for item in items} <= {"log", "event"}
        for event in usage_events:
            assert set(event) == {
                "timestamp", "trace_id", "level", "body", "attributes",
            }
            assert event["level"] == "info"
            assert event["body"] in telemetry.USAGE_EVENTS
            expected_attributes = {
                "os", "sentry.release", "sentry.severity_number", "sentry.severity_text",
            }
            if event["body"] in telemetry.COUNTED_EVENTS:
                expected_attributes.add(telemetry.COUNTED_EVENTS[event["body"]])
            assert set(event["attributes"]) == expected_attributes
        if usage:
            assert usage_events[0]["attributes"]["photo_count"] == {"value": 3, "type": "integer"}
            assert usage_events[1]["attributes"]["photo_count"] == {"value": 2, "type": "integer"}
            assert usage_events[5]["attributes"]["scan_count"] == {"value": 4, "type": "integer"}
            assert len({event["trace_id"] for event in usage_events}) == 6
        serialized = b"".join(envelope.serialize() for envelope in envelopes)
        assert b"private" not in serialized and b"secret-photo" not in serialized
        envelope_count = len(envelopes)
        telemetry.configure(False)
        telemetry.capture_usage("app_opened")
        telemetry.capture_exception(ValueError("secret"))
        assert len(envelopes) == envelope_count
    finally:
        telemetry.configure(False)


def test_usage_filter_reconstructs_payload_and_blocks_other_channel(monkeypatch):
    monkeypatch.setattr(telemetry, "_usage_enabled", True)
    monkeypatch.setattr(telemetry, "_crashes_enabled", False)
    event = {
        "body": "photos_saved",
        "time_unix_nano": 123456789,
        "trace_id": "private-session",
        "attributes": {
            "photo_count": 2, "path": "/private/photo.jpg",
            "server.address": "private-machine", "user.id": "private",
            "sentry.trace.parent_span_id": "private-parent",
        },
        "extra": {"image": "pixels"}, "user": {"id": "private"},
        "request": {"url": "secret"}, "breadcrumbs": [{"message": "secret"}],
        "contexts": {"device": {"id": "private"}}, "server_name": "private",
    }
    filtered = telemetry._filter_log(event, {})
    assert filtered["body"] == "photos_saved"
    assert filtered["attributes"]["photo_count"] == 2
    assert "private" not in str(filtered) and "pixels" not in str(filtered)
    assert telemetry._filter_event({"exception": {"values": []}}, {}) is None
    assert telemetry._filter_event({"message": "unapproved"}, {}) is None
    assert telemetry._filter_event({"message": "app_opened"}, {}) is None
    assert telemetry._filter_log({"body": "unapproved"}, {}) is None


def test_real_log_envelope_strips_ambient_sdk_context_and_restores_scope(monkeypatch):
    import sentry_sdk
    from sentry_sdk.transport import Transport

    envelopes = []

    class RecordingTransport(Transport):
        def capture_envelope(self, envelope):
            envelopes.append(envelope)

    original_client = sentry_sdk.Client

    def offline_client(**options):
        options["transport"] = RecordingTransport
        options["server_name"] = "private-host"
        return original_client(**options)

    monkeypatch.setattr(sentry_sdk, "Client", offline_client)
    original_scope = sentry_sdk.get_current_scope()
    try:
        telemetry.configure(False, True)
        with sentry_sdk.isolation_scope() as scope:
            scope.set_user({"id": "private-id", "email": "private@example.com"})
            telemetry.capture_usage("photos_saved", 2)
        assert sentry_sdk.get_current_scope() is original_scope
        # No global client binding: unrelated logger calls are not forwarded.
        sentry_sdk.logger.info("private unrelated log")
        telemetry.shutdown()
        assert len(envelopes) == 1
        item = envelopes[0].items[0]
        assert item.headers["type"] == "log"
        logs = item.payload.json["items"]
        assert len(logs) == 1
        assert logs[0]["body"] == "photos_saved"
        assert b"private" not in envelopes[0].serialize()
        assert "trace_id" in logs[0] and "user.id" not in logs[0]["attributes"]
    finally:
        telemetry.configure(False)


def test_disabled_usage_filter_rejects_even_allowlisted_logs(monkeypatch):
    monkeypatch.setattr(telemetry, "_usage_enabled", False)
    assert telemetry._filter_log({"body": "app_opened", "time_unix_nano": 123}, {}) is None


def test_revocation_drops_buffered_logs_before_delivery(monkeypatch):
    from sentry_sdk.transport import HttpTransport

    delivered = []
    monkeypatch.setattr(
        HttpTransport, "_send_envelope", lambda self, envelope: delivered.append(envelope)
    )
    try:
        telemetry.configure(False, True)
        old_transport = telemetry._client.transport
        telemetry.capture_usage("app_opened")
        telemetry.configure(False)
        # Flush also executes during client close, so this covers buffered log batches.
        old_transport._worker.flush(timeout=1)
        assert not delivered
    finally:
        telemetry.configure(False)


@pytest.mark.parametrize("name,count", [
    ("unknown", None), ("photos_saved", None), ("photos_saved", 0),
    ("photos_saved", True), ("photos_extracted", -1), ("app_opened", 1),
    ("batch_started", None), ("batch_started", 0),
])
def test_usage_rejects_invalid_event_data(name, count):
    with pytest.raises(ValueError):
        telemetry.capture_usage(name, count)


def test_revocation_blocks_already_queued_transport_delivery(monkeypatch):
    import sentry_sdk
    from sentry_sdk.transport import HttpTransport

    clients = []
    delivered = []
    queued = []
    original_client = sentry_sdk.Client

    def offline_client(**options):
        client = original_client(**options)
        clients.append(client)
        return client

    monkeypatch.setattr(sentry_sdk, "Client", offline_client)
    monkeypatch.setattr(HttpTransport, "capture_envelope", lambda self, envelope: queued.append(envelope))
    monkeypatch.setattr(HttpTransport, "_send_envelope", lambda self, envelope: delivered.append(envelope))
    telemetry.configure(False)
    try:
        telemetry.configure(True, True)
        old_transport = clients[-1].transport
        telemetry.capture_usage("app_opened")
        telemetry.capture_exception(ValueError("private"))
        clients[-1].flush(timeout=1)
        assert len(queued) == 2
        telemetry.configure(False, True)
        for envelope in queued:
            old_transport._send_envelope(envelope)
        assert not delivered
        telemetry.capture_usage("app_opened")
        clients[-1].flush(timeout=1)
        clients[-1].transport._send_envelope(queued[-1])
        assert len(delivered) == 1
        telemetry.capture_exception(ValueError("private"))
        assert len(queued) == 3
        telemetry.configure(True, False)
        telemetry.capture_usage("app_opened")
        assert len(queued) == 3
        telemetry.capture_exception(ValueError("private"))
        assert len(queued) == 4
    finally:
        telemetry.configure(False)
