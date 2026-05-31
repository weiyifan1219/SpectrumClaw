"""Memory service — high-level read/write operations for the agent runtime."""

from __future__ import annotations

import uuid
from typing import Any

from .models import (
    EvolutionReport,
    MemoryEvent,
    MemoryFeedback,
    MemoryItem,
    MemoryOverview,
    MemoryThread,
    SkillRun,
    _now,
)
from .store import MemoryStore


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class MemoryService:
    """Thin service layer over MemoryStore.

    Writer methods are designed to fail gracefully — they return bool
    and never raise, so memory failures don't block the main flow.
    """

    def __init__(self, store: MemoryStore | None = None, db_path: str = "data/memory/spectrum_memory.sqlite3") -> None:
        self._store = store or MemoryStore(db_path)

    @property
    def store(self) -> MemoryStore:
        return self._store

    # ── thread ──

    def ensure_thread(self, thread_id: str, title: str = "") -> MemoryThread:
        existing = self._store.get_thread(thread_id)
        if existing:
            return existing
        t = MemoryThread(thread_id=thread_id, title=title or f"Session {thread_id[:8]}")
        try:
            self._store.upsert_thread(t)
        except Exception:
            pass
        return t

    def bump_thread(self, thread_id: str, summary: str = "") -> None:
        existing = self._store.get_thread(thread_id)
        if existing is None:
            return
        existing.updated_at = _now()
        existing.turn_count += 1
        if summary:
            existing.summary = summary
        try:
            self._store.upsert_thread(existing)
        except Exception:
            pass

    # ── events ──

    def record_event(
        self,
        thread_id: str,
        event_type: str,
        role: str = "",
        content: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> str | None:
        import json as _json

        event_id = _uid("evt")
        evt = MemoryEvent(
            event_id=event_id,
            thread_id=thread_id,
            event_type=event_type,  # type: ignore[arg-type]
            role=role,
            content=content[:4000],
            metadata_json=_json.dumps(metadata or {}, ensure_ascii=False),
        )
        try:
            self._store.insert_event(evt)
            return event_id
        except Exception:
            return None

    # ── memory items ──

    def add_memory(
        self,
        text: str,
        kind: str = "episodic",
        thread_id: str = "",
        skill_name: str = "",
        tags: list[str] | None = None,
        confidence: float = 0.5,
        source_event_id: str = "",
    ) -> str | None:
        import json as _json

        memory_id = _uid("mem")
        item = MemoryItem(
            memory_id=memory_id,
            kind=kind,  # type: ignore[arg-type]
            text=text,
            summary=text[:200],
            confidence=confidence,
            source_event_id=source_event_id,
            thread_id=thread_id,
            skill_name=skill_name,
            tags_json=_json.dumps(tags or [], ensure_ascii=False),
        )
        try:
            self._store.insert_item(item)
            return memory_id
        except Exception:
            return None

    def search_memories(
        self,
        kind: str | None = None,
        thread_id: str | None = None,
        skill_name: str | None = None,
        tag: str | None = None,
        limit: int = 20,
    ) -> list[MemoryItem]:
        try:
            return self._store.query_items(
                kind=kind, thread_id=thread_id,
                skill_name=skill_name, tag=tag, limit=limit,
            )
        except Exception:
            return []

    # ── skill runs ──

    def record_skill_run(
        self,
        skill_name: str,
        thread_id: str = "",
        input_data: dict[str, Any] | None = None,
        output_summary: str = "",
        status: str = "pending",
        latency_ms: int = 0,
        error: str = "",
        rag_refs: list[str] | None = None,
    ) -> str | None:
        import json as _json

        run_id = _uid("run")
        run = SkillRun(
            run_id=run_id,
            thread_id=thread_id,
            skill_name=skill_name,
            input_json=_json.dumps(input_data or {}, ensure_ascii=False),
            output_summary=output_summary,
            status=status,
            latency_ms=latency_ms,
            error=error,
            rag_refs_json=_json.dumps(rag_refs or [], ensure_ascii=False),
        )
        try:
            self._store.insert_skill_run(run)
            return run_id
        except Exception:
            return None

    # ── feedback ──

    def record_feedback(
        self,
        target_type: str,
        target_id: str,
        rating: int = 0,
        comment: str = "",
    ) -> str | None:
        fb = MemoryFeedback(
            feedback_id=_uid("fb"),
            target_type=target_type,
            target_id=target_id,
            rating=rating,
            comment=comment,
        )
        try:
            self._store.insert_feedback(fb)
            return fb.feedback_id
        except Exception:
            return None

    # ── evolution ──

    def add_report(
        self,
        summary: str,
        period: str = "",
        metrics: dict[str, Any] | None = None,
        suggestions: list[dict[str, Any]] | None = None,
    ) -> str | None:
        import json as _json

        report = EvolutionReport(
            report_id=_uid("rpt"),
            period=period,
            summary=summary,
            metrics_json=_json.dumps(metrics or {}, ensure_ascii=False),
            suggestions_json=_json.dumps(suggestions or [], ensure_ascii=False),
        )
        try:
            self._store.insert_report(report)
            return report.report_id
        except Exception:
            return None

    # ── overview ──

    def overview(self, enabled: bool = True) -> MemoryOverview:
        try:
            return self._store.overview(enabled=enabled)
        except Exception:
            return MemoryOverview(enabled=False)
