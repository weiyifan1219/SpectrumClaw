from __future__ import annotations

import time
from typing import Any


SCHEMA_VERSION = "agent-run-v1"
CANONICAL_EVENTS = {
    "stage",
    "thinking",
    "content",
    "tool_call",
    "tool_result",
    "rag_result",
    "memory_write",
    "artifact",
    "error",
    "done",
}


def make_event(
    event_type: str,
    data: Any = None,
    *,
    source: str = "agent",
    compat_type: str | None = None,
    status: str | None = None,
    stage: str | None = None,
    label: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": compat_type or event_type,
        "event": event_type,
        "schema_version": SCHEMA_VERSION,
        "source": source,
        "ts": time.time(),
    }
    if data is not None:
        payload["data"] = data
    if status:
        payload["status"] = status
    if stage:
        payload["stage"] = stage
    if label:
        payload["label"] = label
    if metadata:
        payload["metadata"] = metadata
    return payload


def stage(stage_name: str, label: str | None = None, *, source: str = "agent", data: Any = None) -> dict[str, Any]:
    return make_event("stage", data, source=source, status="started", stage=stage_name, label=label)


def stage_done(stage_name: str, *, source: str = "agent", data: Any = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    return make_event(
        "stage",
        data,
        source=source,
        compat_type="stage_done",
        status="done",
        stage=stage_name,
        metadata=metadata,
    )


def thinking(data: str, *, source: str = "agent") -> dict[str, Any]:
    return make_event("thinking", data, source=source)


def content(data: str, *, source: str = "agent") -> dict[str, Any]:
    return make_event("content", data, source=source)


def tool_call(data: dict[str, Any], *, source: str = "agent") -> dict[str, Any]:
    return make_event("tool_call", data, source=source)


def tool_result(data: dict[str, Any], *, source: str = "agent") -> dict[str, Any]:
    return make_event("tool_result", data, source=source)


def rag_result(data: dict[str, Any], *, source: str = "agent") -> dict[str, Any]:
    return make_event("rag_result", data, source=source)


def memory_write(data: dict[str, Any], *, source: str = "agent") -> dict[str, Any]:
    return make_event("memory_write", data, source=source)


def artifact(data: dict[str, Any], *, source: str = "agent") -> dict[str, Any]:
    return make_event("artifact", data, source=source)


def done(data: dict[str, Any], *, source: str = "agent") -> dict[str, Any]:
    return make_event("done", data, source=source, status="done")


def error(data: str, *, source: str = "agent") -> dict[str, Any]:
    return make_event("error", data, source=source, status="error")


def standardize_event(raw: dict[str, Any], *, source: str = "agent") -> dict[str, Any]:
    """Add the run-event contract fields while preserving legacy keys."""
    if raw.get("schema_version") == SCHEMA_VERSION:
        return raw

    event = dict(raw)
    compat_type = str(event.get("type", "event"))
    canonical = _canonical_event_type(compat_type)
    event.setdefault("event", canonical)
    event.setdefault("schema_version", SCHEMA_VERSION)
    event.setdefault("source", source)
    event.setdefault("ts", time.time())

    if compat_type == "stage":
        event.setdefault("status", "started")
    elif compat_type == "stage_done":
        event.setdefault("status", "done")
    elif compat_type == "done":
        event.setdefault("status", "done")
        if "data" not in event:
            event["data"] = {
                key: value for key, value in event.items()
                if key not in {"type", "event", "schema_version", "source", "ts", "status"}
            }
    elif compat_type == "error":
        event.setdefault("status", "error")

    return event


def _canonical_event_type(compat_type: str) -> str:
    if compat_type == "stage_done":
        return "stage"
    if compat_type in CANONICAL_EVENTS:
        return compat_type
    return compat_type
