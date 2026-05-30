"""Processing callbacks for RAG pipeline observability.

Aligned with RAG-Anything's raganything/callbacks.py:
provides ProcessingCallback / CallbackManager for event-driven progress tracking.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class ProcessingEvent:
    name: str
    file_path: str = ""
    status: str = "started"  # started | progress | completed | failed
    progress: float = 0.0    # 0.0 to 1.0
    message: str = ""
    metadata: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


class CallbackManager:
    """Dispatches processing events to registered callbacks.

    Usage:
        mgr = CallbackManager()
        mgr.register(lambda event: print(f"[{event.name}] {event.message}"))
        mgr.emit("parse_start", file_path="doc.pdf")
    """

    def __init__(self):
        self._callbacks: list[Callable[[ProcessingEvent], Any]] = []
        self._events: list[ProcessingEvent] = []  # event log

    def register(self, callback: Callable[[ProcessingEvent], Any]):
        self._callbacks.append(callback)

    def emit(self, name: str, file_path: str = "", status: str = "started",
             progress: float = 0.0, message: str = "", **meta):
        event = ProcessingEvent(
            name=name, file_path=file_path, status=status,
            progress=progress, message=message, metadata=meta,
        )
        self._events.append(event)
        for cb in self._callbacks:
            try:
                cb(event)
            except Exception:
                pass

    @property
    def events(self) -> list[dict]:
        return [{"name": e.name, "file_path": e.file_path, "status": e.status,
                 "progress": e.progress, "message": e.message,
                 "timestamp": e.timestamp} for e in self._events]

    def clear(self):
        self._events.clear()
