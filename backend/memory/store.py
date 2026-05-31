"""SQLite store for memory system — plain sqlite3, no ORM."""

from __future__ import annotations

import json as _json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from .models import (
    EvolutionReport,
    MemoryEvent,
    MemoryFeedback,
    MemoryItem,
    MemoryOverview,
    MemoryThread,
    SkillRun,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_threads (
    thread_id   TEXT PRIMARY KEY,
    title       TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    summary     TEXT NOT NULL DEFAULT '',
    turn_count  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS memory_events (
    event_id      TEXT PRIMARY KEY,
    thread_id     TEXT NOT NULL,
    event_type    TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT '',
    content       TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_items (
    memory_id       TEXT PRIMARY KEY,
    scope           TEXT NOT NULL DEFAULT 'workspace',
    kind            TEXT NOT NULL DEFAULT 'episodic',
    text            TEXT NOT NULL,
    summary         TEXT NOT NULL DEFAULT '',
    confidence      REAL NOT NULL DEFAULT 0.5,
    source_event_id TEXT NOT NULL DEFAULT '',
    thread_id       TEXT NOT NULL DEFAULT '',
    skill_name      TEXT NOT NULL DEFAULT '',
    tags_json       TEXT NOT NULL DEFAULT '[]',
    valid_from      TEXT NOT NULL,
    valid_to        TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS skill_runs (
    run_id        TEXT PRIMARY KEY,
    thread_id     TEXT NOT NULL DEFAULT '',
    skill_name    TEXT NOT NULL,
    input_json    TEXT NOT NULL DEFAULT '{}',
    output_summary TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'pending',
    latency_ms    INTEGER NOT NULL DEFAULT 0,
    error         TEXT NOT NULL DEFAULT '',
    rag_refs_json TEXT NOT NULL DEFAULT '[]',
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_feedback (
    feedback_id TEXT PRIMARY KEY,
    target_type TEXT NOT NULL,
    target_id   TEXT NOT NULL,
    rating      INTEGER NOT NULL DEFAULT 0,
    comment     TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evolution_reports (
    report_id       TEXT PRIMARY KEY,
    period          TEXT NOT NULL DEFAULT '',
    summary         TEXT NOT NULL DEFAULT '',
    metrics_json    TEXT NOT NULL DEFAULT '{}',
    suggestions_json TEXT NOT NULL DEFAULT '[]',
    status          TEXT NOT NULL DEFAULT 'pending',
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_thread ON memory_events(thread_id, created_at);
CREATE INDEX IF NOT EXISTS idx_items_kind ON memory_items(kind, created_at);
CREATE INDEX IF NOT EXISTS idx_items_thread ON memory_items(thread_id);
CREATE INDEX IF NOT EXISTS idx_skill_runs_name ON skill_runs(skill_name, created_at);
CREATE INDEX IF NOT EXISTS idx_feedback_target ON memory_feedback(target_type, target_id);
"""


class MemoryStore:
    """Thread-safe SQLite store for the memory system."""

    def __init__(self, db_path: str = "data/memory/spectrum_memory.sqlite3") -> None:
        self.db_path = Path(db_path)
        self._lock = threading.Lock()
        self._init_db()

    # ── init ──

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._connect() as conn:
            conn.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=OFF")
        return conn

    # ── threads ──

    def upsert_thread(self, thread: MemoryThread) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT INTO memory_threads (thread_id, title, created_at, updated_at, summary, turn_count)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(thread_id) DO UPDATE SET
                       title=excluded.title, updated_at=excluded.updated_at,
                       summary=excluded.summary, turn_count=excluded.turn_count""",
                (thread.thread_id, thread.title, thread.created_at,
                 thread.updated_at, thread.summary, thread.turn_count),
            )

    def get_thread(self, thread_id: str) -> MemoryThread | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM memory_threads WHERE thread_id=?", (thread_id,)
            ).fetchone()
        if row is None:
            return None
        return MemoryThread(**dict(row))

    def list_threads(self, limit: int = 20) -> list[MemoryThread]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM memory_threads ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [MemoryThread(**dict(r)) for r in rows]

    # ── events ──

    def insert_event(self, event: MemoryEvent) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT INTO memory_events (event_id, thread_id, event_type, role, content, metadata_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (event.event_id, event.thread_id, event.event_type, event.role,
                 event.content, event.metadata_json, event.created_at),
            )

    def list_events(self, thread_id: str, limit: int = 50) -> list[MemoryEvent]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM memory_events WHERE thread_id=? ORDER BY created_at ASC LIMIT ?",
                (thread_id, limit),
            ).fetchall()
        return [MemoryEvent(**dict(r)) for r in rows]

    # ── items ──

    def insert_item(self, item: MemoryItem) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT INTO memory_items
                   (memory_id, scope, kind, text, summary, confidence,
                    source_event_id, thread_id, skill_name, tags_json,
                    valid_from, valid_to, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (item.memory_id, item.scope, item.kind, item.text, item.summary,
                 item.confidence, item.source_event_id, item.thread_id,
                 item.skill_name, item.tags_json, item.valid_from, item.valid_to,
                 item.created_at, item.updated_at),
            )

    def query_items(
        self,
        kind: str | None = None,
        thread_id: str | None = None,
        skill_name: str | None = None,
        tag: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MemoryItem]:
        clauses: list[str] = []
        params: list[Any] = []
        if kind:
            clauses.append("kind=?")
            params.append(kind)
        if thread_id:
            clauses.append("thread_id=?")
            params.append(thread_id)
        if skill_name:
            clauses.append("skill_name=?")
            params.append(skill_name)
        if tag:
            clauses.append("tags_json LIKE ?")
            params.append(f"%{tag}%")

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT * FROM memory_items {where} ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with self._lock, self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [MemoryItem(**dict(r)) for r in rows]

    def count_items_by_kind(self) -> dict[str, int]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT kind, COUNT(*) as cnt FROM memory_items GROUP BY kind"
            ).fetchall()
        return {r["kind"]: r["cnt"] for r in rows}

    def delete_item(self, memory_id: str) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM memory_items WHERE memory_id=?", (memory_id,))
            return cur.rowcount > 0

    # ── skill runs ──

    def insert_skill_run(self, run: SkillRun) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT INTO skill_runs
                   (run_id, thread_id, skill_name, input_json, output_summary,
                    status, latency_ms, error, rag_refs_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (run.run_id, run.thread_id, run.skill_name, run.input_json,
                 run.output_summary, run.status, run.latency_ms, run.error,
                 run.rag_refs_json, run.created_at),
            )

    def list_skill_runs(self, skill_name: str = "", limit: int = 20) -> list[SkillRun]:
        with self._lock, self._connect() as conn:
            if skill_name:
                rows = conn.execute(
                    "SELECT * FROM skill_runs WHERE skill_name=? ORDER BY created_at DESC LIMIT ?",
                    (skill_name, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM skill_runs ORDER BY created_at DESC LIMIT ?", (limit,)
                ).fetchall()
        return [SkillRun(**dict(r)) for r in rows]

    def skill_run_stats(self) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """SELECT skill_name,
                          COUNT(*) as total,
                          SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) as success,
                          AVG(latency_ms) as avg_latency_ms
                   FROM skill_runs GROUP BY skill_name"""
            ).fetchall()
        return [dict(r) for r in rows]

    # ── feedback ──

    def insert_feedback(self, fb: MemoryFeedback) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO memory_feedback (feedback_id, target_type, target_id, rating, comment, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (fb.feedback_id, fb.target_type, fb.target_id, fb.rating, fb.comment, fb.created_at),
            )

    def list_feedback(self, target_type: str = "", limit: int = 20) -> list[MemoryFeedback]:
        with self._lock, self._connect() as conn:
            if target_type:
                rows = conn.execute(
                    "SELECT * FROM memory_feedback WHERE target_type=? ORDER BY created_at DESC LIMIT ?",
                    (target_type, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM memory_feedback ORDER BY created_at DESC LIMIT ?", (limit,)
                ).fetchall()
        return [MemoryFeedback(**dict(r)) for r in rows]

    # ── evolution reports ──

    def insert_report(self, report: EvolutionReport) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT INTO evolution_reports (report_id, period, summary, metrics_json, suggestions_json, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (report.report_id, report.period, report.summary,
                 report.metrics_json, report.suggestions_json, report.status, report.created_at),
            )

    def list_reports(self, limit: int = 10) -> list[EvolutionReport]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM evolution_reports ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [EvolutionReport(**dict(r)) for r in rows]

    # ── overview ──

    def overview(self, enabled: bool = True) -> MemoryOverview:
        with self._lock, self._connect() as conn:
            thread_count = conn.execute("SELECT COUNT(*) FROM memory_threads").fetchone()[0]
            event_count = conn.execute("SELECT COUNT(*) FROM memory_events").fetchone()[0]
            item_count = conn.execute("SELECT COUNT(*) FROM memory_items").fetchone()[0]
            skill_run_count = conn.execute("SELECT COUNT(*) FROM skill_runs").fetchone()[0]
            feedback_count = conn.execute("SELECT COUNT(*) FROM memory_feedback").fetchone()[0]
            kind_rows = conn.execute(
                "SELECT kind, COUNT(*) as cnt FROM memory_items GROUP BY kind"
            ).fetchall()
            kinds = {r["kind"]: r["cnt"] for r in kind_rows}
            last = conn.execute("SELECT MAX(updated_at) FROM memory_items").fetchone()[0]
        return MemoryOverview(
            enabled=enabled,
            thread_count=thread_count,
            event_count=event_count,
            item_count=item_count,
            episodic_count=kinds.get("episodic", 0),
            skill_count=kinds.get("skill", 0),
            domain_count=kinds.get("domain", 0),
            evolution_count=kinds.get("evolution", 0),
            skill_run_count=skill_run_count,
            feedback_count=feedback_count,
            last_updated=last or "",
            db_path=str(self.db_path),
        )
