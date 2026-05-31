"""Pydantic models for memory system — matching SQLite schema from docs/MEMORY_AND_EVOLUTION.md §7."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


EventType = Literal["user", "assistant", "tool", "rag", "error", "feedback", "system"]
MemoryKind = Literal["episodic", "skill", "domain", "evolution"]
MemoryScope = Literal["workspace", "thread"]


class MemoryThread(BaseModel):
    thread_id: str
    title: str = ""
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)
    summary: str = ""
    turn_count: int = 0


class MemoryEvent(BaseModel):
    event_id: str
    thread_id: str
    event_type: EventType
    role: str = ""
    content: str = ""
    metadata_json: str = "{}"
    created_at: str = Field(default_factory=_now)


class MemoryItem(BaseModel):
    memory_id: str
    scope: MemoryScope = "workspace"
    kind: MemoryKind = "episodic"
    text: str
    summary: str = ""
    confidence: float = 0.5
    source_event_id: str = ""
    thread_id: str = ""
    skill_name: str = ""
    tags_json: str = "[]"
    valid_from: str = Field(default_factory=_now)
    valid_to: str | None = None
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)

    @property
    def tags(self) -> list[str]:
        import json as _json

        try:
            return _json.loads(self.tags_json)
        except Exception:
            return []


class SkillRun(BaseModel):
    run_id: str
    thread_id: str = ""
    skill_name: str
    input_json: str = "{}"
    output_summary: str = ""
    status: str = "pending"
    latency_ms: int = 0
    error: str = ""
    rag_refs_json: str = "[]"
    created_at: str = Field(default_factory=_now)


class MemoryFeedback(BaseModel):
    feedback_id: str
    target_type: str
    target_id: str
    rating: int = 0
    comment: str = ""
    created_at: str = Field(default_factory=_now)


class EvolutionReport(BaseModel):
    report_id: str
    period: str = ""
    summary: str = ""
    metrics_json: str = "{}"
    suggestions_json: str = "[]"
    status: str = "pending"
    created_at: str = Field(default_factory=_now)


class MemoryOverview(BaseModel):
    enabled: bool
    thread_count: int = 0
    event_count: int = 0
    item_count: int = 0
    episodic_count: int = 0
    skill_count: int = 0
    domain_count: int = 0
    evolution_count: int = 0
    skill_run_count: int = 0
    feedback_count: int = 0
    last_updated: str = ""
    db_path: str = ""
