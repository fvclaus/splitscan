from __future__ import annotations

import logging
import platform
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sentry_sdk import Client, Scope

DSN = "https://5f9f01064f5c75f947cfa41727b9b100@o4511513929449472.ingest.de.sentry.io/4512230804881489"
_client: Client | None = None
_scope: Scope | None = None


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


def configure(enabled: bool) -> None:
    global _client, _scope
    if not enabled:
        client, _client = _client, None
        _scope = None
        if client is not None:
            client.close(timeout=0)
        return
    if _client is not None:
        return
    import sentry_sdk
    from photo_splitter.version import __version__

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
        before_send=sanitize_event,
        max_breadcrumbs=0,
    )
    scope = sentry_sdk.Scope()
    scope.set_client(client)
    _scope, _client = scope, client


def capture_exception(exception: BaseException) -> None:
    client, scope = _client, _scope
    if client is not None and scope is not None:
        try:
            from sentry_sdk.utils import event_from_exception

            event, hint = event_from_exception(exception, client_options=client.options)
            client.capture_event(event, hint=hint, scope=scope)
        except Exception:
            logging.exception("Could not submit sanitized crash report")


def shutdown() -> None:
    if _client is not None:
        _client.flush(timeout=1)
    configure(False)
