from __future__ import annotations

import logging
import platform
import re
from threading import Event
from typing import TYPE_CHECKING, Any
from uuid import uuid4

if TYPE_CHECKING:
    from sentry_sdk import Client, Scope

DSN = "https://5f9f01064f5c75f947cfa41727b9b100@o4511513929449472.ingest.de.sentry.io/4512230804881489"
_client: Client | None = None
_scope: Scope | None = None
_crashes_enabled = False
_usage_enabled = False
_delivery_allowed = Event()
USAGE_EVENTS = frozenset({
    "app_opened", "scan_loaded", "boundary_corrected", "photos_extracted", "photos_saved",
})
COUNTED_EVENTS = frozenset({"photos_extracted", "photos_saved"})


def sanitize_event(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any]:
    from photo_splitter.version import __version__

    exceptions = []
    for value in event.get("exception", {}).get("values", []):
        frames = []
        for frame in value.get("stacktrace", {}).get("frames", []):
            module = frame.get("module", "")
            if isinstance(module, str) and (
                module == "photo_splitter" or module.startswith("photo_splitter.")
            ) and re.fullmatch(r"[a-z_]+(?:\.[a-z_]+)*", module):
                frames.append({
                    "module": module,
                    "filename": module.replace(".", "/") + ".py",
                    "lineno": frame.get("lineno"),
                    "in_app": True,
                })
        exception_type = value.get("type", "Error")
        if not isinstance(exception_type, str) or not exception_type.isidentifier():
            exception_type = "Error"
        exceptions.append({
            "type": exception_type,
            "value": "Diagnostic details removed for privacy",
            "stacktrace": {"frames": frames},
        })
    return {
        "event_id": event.get("event_id"),
        "timestamp": event.get("timestamp"),
        "platform": "python",
        "level": "error",
        "release": f"SplitScan@{__version__}",
        "tags": {"os": platform.system()},
        "exception": {"values": exceptions},
    }


def _filter_event(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any] | None:
    return sanitize_event(event, hint) if _crashes_enabled and "exception" in event else None


def _filter_log(log: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any] | None:
    name = log.get("body")
    if not _usage_enabled or not isinstance(name, str) or name not in USAGE_EVENTS:
        return None
    from photo_splitter.version import __version__

    attributes: dict[str, str | int] = {
        "os": platform.system(),
        "sentry.release": f"SplitScan@{__version__}",
    }
    if name in COUNTED_EVENTS:
        count = log.get("attributes", {}).get("photo_count")
        if type(count) is not int or count <= 0:
            raise ValueError("Usage photo count must be a positive integer.")
        attributes["photo_count"] = count
    return {
        "time_unix_nano": log["time_unix_nano"],
        # Avoid linking usage records through SDK-generated session/trace context.
        "trace_id": uuid4().hex,
        "severity_text": "info",
        "severity_number": 9,
        "body": name,
        "attributes": attributes,
    }


def configure(enabled: bool, usage: bool = False) -> None:
    global _client, _scope, _crashes_enabled, _usage_enabled, _delivery_allowed
    if (_crashes_enabled, _usage_enabled) == (enabled, usage) and (
        (_client is not None and (enabled or usage))
        or (_client is None and not (enabled or usage))
    ):
        return
    _delivery_allowed.clear()
    client, _client = _client, None
    _scope = None
    _crashes_enabled = _usage_enabled = False
    if client is not None:
        client.close(timeout=0)
    if not (enabled or usage):
        return
    import sentry_sdk
    from sentry_sdk.transport import HttpTransport
    from photo_splitter.version import __version__

    delivery_allowed = Event()

    class ConsentTransport(HttpTransport):
        def _send_envelope(self, envelope):
            # SDK close queues a terminator behind pending events, so guard actual delivery.
            if delivery_allowed.is_set():
                super()._send_envelope(envelope)

    client = sentry_sdk.Client(
        dsn=DSN,
        release=f"SplitScan@{__version__}",
        send_default_pii=False,
        include_local_variables=False,
        default_integrations=False,
        auto_enabling_integrations=False,
        debug=False,
        spotlight=False,
        auto_session_tracking=False,
        send_client_reports=False,
        traces_sample_rate=0,
        profiles_sample_rate=0,
        before_send=_filter_event,
        enable_logs=usage,
        before_send_log=_filter_log,
        max_breadcrumbs=0,
        transport=ConsentTransport,
    )
    scope = sentry_sdk.Scope()
    scope.set_client(client)
    _scope, _client = scope, client
    _crashes_enabled, _usage_enabled = enabled, usage
    _delivery_allowed = delivery_allowed
    delivery_allowed.set()


def capture_exception(exception: BaseException) -> None:
    client, scope = _client, _scope
    if _crashes_enabled and client is not None and scope is not None:
        try:
            from sentry_sdk.utils import event_from_exception

            event, hint = event_from_exception(exception, client_options=client.options)
            client.capture_event(event, hint=hint, scope=scope)
        except Exception:
            logging.exception("Could not submit sanitized crash report")


def capture_usage(name: str, photo_count: int | None = None) -> None:
    if name not in USAGE_EVENTS:
        raise ValueError(f"Unknown usage event: {name}")
    if name in COUNTED_EVENTS:
        if type(photo_count) is not int or photo_count <= 0:
            raise ValueError("Usage photo count must be a positive integer.")
    elif photo_count is not None:
        raise ValueError("This usage event does not accept a photo count.")
    client, scope = _client, _scope
    if _usage_enabled and client is not None and scope is not None:
        try:
            from sentry_sdk import logger
            from sentry_sdk.scope import use_scope

            attributes = {"photo_count": photo_count} if photo_count is not None else {}
            with use_scope(scope):
                logger.info(name, attributes=attributes)
        except Exception:
            logging.exception("Could not submit usage statistics")


def shutdown() -> None:
    if _client is not None:
        _client.flush(timeout=1)
    configure(False)
