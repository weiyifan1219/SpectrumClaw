"""Map internal agent events to SSE-compatible dicts."""

from __future__ import annotations

from typing import Any

from . import run_events


stage = run_events.stage
stage_done = run_events.stage_done
tool_call = run_events.tool_call
tool_result = run_events.tool_result
rag_result = run_events.rag_result
memory_write = run_events.memory_write
artifact = run_events.artifact
standardize_event = run_events.standardize_event


def thinking(data: str, *, source: str = "agent") -> dict[str, Any]:
    return run_events.thinking(data, source=source)


def content(data: str, *, source: str = "agent") -> dict[str, Any]:
    return run_events.content(data, source=source)


def done(meta: dict[str, Any], *, source: str = "agent") -> dict[str, Any]:
    return run_events.done(meta, source=source)


def error(data: str, *, source: str = "agent") -> dict[str, Any]:
    return run_events.error(data, source=source)
