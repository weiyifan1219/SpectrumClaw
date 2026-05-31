"""Tests for memory store — schema init, CRUD, queries by kind/tag/thread."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.memory.models import (
    EvolutionReport,
    MemoryEvent,
    MemoryFeedback,
    MemoryItem,
    MemoryThread,
    SkillRun,
)
from backend.memory.store import MemoryStore


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Path(tmpdir) / "test_memory.sqlite3"
        s = MemoryStore(str(db))
        yield s


class TestSchemaInit:
    def test_tables_created(self, store):
        with store._connect() as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        names = {r["name"] for r in tables}
        for t in ("memory_threads", "memory_events", "memory_items",
                  "skill_runs", "memory_feedback", "evolution_reports"):
            assert t in names

    def test_idempotent_init(self, store):
        store._init_db()  # second call should not fail
        with store._connect() as conn:
            cnt = conn.execute("SELECT COUNT(*) FROM memory_threads").fetchone()[0]
        assert cnt == 0


class TestThreads:
    def test_upsert_and_get(self, store):
        t = MemoryThread(thread_id="th1", title="Test session")
        store.upsert_thread(t)
        got = store.get_thread("th1")
        assert got is not None
        assert got.title == "Test session"
        assert got.turn_count == 0

    def test_upsert_updates(self, store):
        t = MemoryThread(thread_id="th1", title="Original")
        store.upsert_thread(t)
        t.title = "Updated"
        t.turn_count = 3
        store.upsert_thread(t)
        got = store.get_thread("th1")
        assert got.title == "Updated"
        assert got.turn_count == 3

    def test_get_nonexistent(self, store):
        assert store.get_thread("nonexistent") is None

    def test_list_threads(self, store):
        for i in range(5):
            store.upsert_thread(MemoryThread(thread_id=f"th{i}", title=f"Session {i}"))
        results = store.list_threads(limit=3)
        assert len(results) == 3

    def test_list_threads_empty(self, store):
        assert store.list_threads() == []


class TestEvents:
    def test_insert_and_list(self, store):
        store.insert_event(MemoryEvent(
            event_id="evt1", thread_id="th1", event_type="user",
            role="user", content="hello",
        ))
        store.insert_event(MemoryEvent(
            event_id="evt2", thread_id="th1", event_type="assistant",
            role="assistant", content="hi there",
        ))
        events = store.list_events("th1")
        assert len(events) == 2
        assert events[0].role == "user"
        assert events[1].role == "assistant"

    def test_list_events_limit(self, store):
        for i in range(10):
            store.insert_event(MemoryEvent(
                event_id=f"evt{i}", thread_id="th1", event_type="user",
            ))
        assert len(store.list_events("th1", limit=5)) == 5

    def test_events_isolated_by_thread(self, store):
        store.insert_event(MemoryEvent(event_id="e1", thread_id="th1", event_type="user"))
        store.insert_event(MemoryEvent(event_id="e2", thread_id="th2", event_type="user"))
        assert len(store.list_events("th1")) == 1
        assert len(store.list_events("th2")) == 1


class TestItems:
    def _make_item(self, **kwargs):
        defaults = dict(
            memory_id="mem1", kind="episodic", text="RAG query about 2.4GHz",
            summary="Frequency planning query", confidence=0.82,
            thread_id="th1", skill_name="frequency_planning",
            tags_json='["rag","frequency","itu"]',
        )
        defaults.update(kwargs)
        return MemoryItem(**defaults)

    def test_insert_and_query_by_kind(self, store):
        store.insert_item(self._make_item(memory_id="mem1", kind="episodic"))
        store.insert_item(self._make_item(memory_id="mem2", kind="skill"))
        store.insert_item(self._make_item(memory_id="mem3", kind="domain"))

        episodic = store.query_items(kind="episodic")
        assert len(episodic) == 1
        assert episodic[0].memory_id == "mem1"

        skill = store.query_items(kind="skill")
        assert len(skill) == 1

    def test_query_by_thread(self, store):
        store.insert_item(self._make_item(memory_id="mem1", thread_id="th1"))
        store.insert_item(self._make_item(memory_id="mem2", thread_id="th2"))
        assert len(store.query_items(thread_id="th1")) == 1

    def test_query_by_tag(self, store):
        store.insert_item(self._make_item(memory_id="mem1", tags_json='["rag","itu"]'))
        store.insert_item(self._make_item(memory_id="mem2", tags_json='["web","news"]'))
        results = store.query_items(tag="itu")
        assert len(results) == 1
        assert results[0].memory_id == "mem1"

    def test_query_by_skill_name(self, store):
        store.insert_item(self._make_item(memory_id="mem1", skill_name="freq_plan"))
        store.insert_item(self._make_item(memory_id="mem2", skill_name="interference"))
        results = store.query_items(skill_name="freq_plan")
        assert len(results) == 1

    def test_count_by_kind(self, store):
        store.insert_item(self._make_item(memory_id="m1", kind="episodic"))
        store.insert_item(self._make_item(memory_id="m2", kind="episodic"))
        store.insert_item(self._make_item(memory_id="m3", kind="domain"))
        counts = store.count_items_by_kind()
        assert counts["episodic"] == 2
        assert counts["domain"] == 1

    def test_delete_item(self, store):
        store.insert_item(self._make_item(memory_id="mem1"))
        assert store.delete_item("mem1") is True
        assert store.delete_item("mem1") is False
        assert store.query_items(kind="episodic") == []

    def test_query_pagination(self, store):
        for i in range(100):
            store.insert_item(self._make_item(memory_id=f"mem{i}"))
        page1 = store.query_items(kind="episodic", limit=50, offset=0)
        page2 = store.query_items(kind="episodic", limit=50, offset=50)
        assert len(page1) == 50
        assert len(page2) == 50

    def test_item_tags_property(self, store):
        store.insert_item(self._make_item(memory_id="mem1", tags_json='["a","b","c"]'))
        items = store.query_items(tag="a")
        assert len(items) == 1
        assert items[0].tags == ["a", "b", "c"]

    def test_item_tags_property_invalid_json(self):
        item = MemoryItem(memory_id="m", text="x", tags_json="not-json")
        assert item.tags == []


class TestSkillRuns:
    def test_insert_and_list(self, store):
        store.insert_skill_run(SkillRun(
            run_id="run1", skill_name="frequency_planning", status="success", latency_ms=1200,
        ))
        store.insert_skill_run(SkillRun(
            run_id="run2", skill_name="interference_analysis", status="failed", error="timeout",
        ))
        all_runs = store.list_skill_runs()
        assert len(all_runs) == 2

    def test_filter_by_skill(self, store):
        store.insert_skill_run(SkillRun(run_id="r1", skill_name="fp"))
        store.insert_skill_run(SkillRun(run_id="r2", skill_name="ia"))
        assert len(store.list_skill_runs(skill_name="fp")) == 1

    def test_stats(self, store):
        store.insert_skill_run(SkillRun(run_id="r1", skill_name="fp", status="success", latency_ms=100))
        store.insert_skill_run(SkillRun(run_id="r2", skill_name="fp", status="failed", latency_ms=200))
        store.insert_skill_run(SkillRun(run_id="r3", skill_name="ia", status="success", latency_ms=50))
        stats = store.skill_run_stats()
        by_name = {s["skill_name"]: s for s in stats}
        assert by_name["fp"]["total"] == 2
        assert by_name["fp"]["success"] == 1
        assert by_name["fp"]["avg_latency_ms"] == 150.0


class TestFeedback:
    def test_insert_and_list(self, store):
        store.insert_feedback(MemoryFeedback(
            feedback_id="fb1", target_type="answer", target_id="evt1", rating=4, comment="Good",
        ))
        store.insert_feedback(MemoryFeedback(
            feedback_id="fb2", target_type="rag", target_id="evt2", rating=2,
        ))
        assert len(store.list_feedback()) == 2
        assert len(store.list_feedback(target_type="rag")) == 1


class TestEvolutionReports:
    def test_insert_and_list(self, store):
        store.insert_report(EvolutionReport(
            report_id="rpt1", period="2026-05-W22", summary="Weekly summary",
            metrics_json='{"tasks":12}', suggestions_json='[{"type":"param"}]',
        ))
        reports = store.list_reports()
        assert len(reports) == 1
        assert reports[0].period == "2026-05-W22"


class TestOverview:
    def test_empty_overview(self, store):
        ov = store.overview()
        assert ov.thread_count == 0
        assert ov.event_count == 0
        assert ov.item_count == 0

    def test_populated_overview(self, store):
        store.upsert_thread(MemoryThread(thread_id="th1"))
        store.insert_event(MemoryEvent(event_id="e1", thread_id="th1", event_type="user"))
        store.insert_item(MemoryItem(memory_id="m1", kind="episodic", text="test"))
        store.insert_item(MemoryItem(memory_id="m2", kind="skill", text="test"))
        store.insert_skill_run(SkillRun(run_id="r1", skill_name="fp"))
        store.insert_feedback(MemoryFeedback(feedback_id="fb1", target_type="answer", target_id="e1"))

        ov = store.overview()
        assert ov.thread_count == 1
        assert ov.event_count == 1
        assert ov.item_count == 2
        assert ov.episodic_count == 1
        assert ov.skill_count == 1
        assert ov.skill_run_count == 1
        assert ov.feedback_count == 1
