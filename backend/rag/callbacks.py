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
    """Dispatches processing events to registered callbacks."""

    def __init__(self):
        self._callbacks: list[Callable[[ProcessingEvent], Any]] = []
        self._events: list[ProcessingEvent] = []
        self._active_file: str = ""
        self._active_started: float = 0.0

    def register(self, callback: Callable[[ProcessingEvent], Any]):
        self._callbacks.append(callback)

    def emit(self, name: str, file_path: str = "", status: str = "started",
             progress: float = 0.0, message: str = "", **meta):
        event = ProcessingEvent(
            name=name, file_path=file_path, status=status,
            progress=progress, message=message, metadata=meta,
        )
        self._events.append(event)
        if file_path:
            self._active_file = file_path
            if status == "started":
                self._active_started = event.timestamp
        for cb in self._callbacks:
            try: cb(event)
            except Exception: pass

    @property
    def events(self) -> list[dict]:
        """Recent events (last 200), newest first."""
        recent = self._events[-200:]
        return [
            {"name": e.name, "file_path": e.file_path, "status": e.status,
             "progress": e.progress, "message": e.message,
             "timestamp": e.timestamp}
            for e in reversed(recent)
        ]

    @property
    def active(self) -> dict:
        """Current active file and progress summary."""
        return {
            "file": self._active_file,
            "elapsed_s": time.time() - self._active_started if self._active_started else 0,
            "total_events": len(self._events),
        }

    def clear(self):
        self._events.clear()
        self._active_file = ""
        self._active_started = 0.0


# Global shared callback manager — accessed by ingest pipeline and API
_shared_callback_manager: CallbackManager | None = None


def get_shared_callback_manager() -> CallbackManager:
    global _shared_callback_manager
    if _shared_callback_manager is None:
        _shared_callback_manager = CallbackManager()
    return _shared_callback_manager


def get_ingest_events() -> dict:
    """Get current ingest progress for API/UI consumption."""
    mgr = get_shared_callback_manager()
    return {
        "active": mgr.active,
        "recent_events": mgr.events[:50],
    }
