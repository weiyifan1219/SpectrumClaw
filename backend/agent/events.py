"""Map internal agent events to SSE-compatible dicts."""

from __future__ import annotations

from typing import Any


def thinking(data: str) -> dict[str, Any]:
    return {"type": "thinking", "data": data}


def content(data: str) -> dict[str, Any]:
    return {"type": "content", "data": data}


def done(meta: dict[str, Any]) -> dict[str, Any]:
    return {"type": "done", "data": meta}


def error(data: str) -> dict[str, Any]:
    return {"type": "error", "data": data}
