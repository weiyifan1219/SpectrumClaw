"""Integration tests for memory API endpoints."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestMemoryApi:
    """Test memory API routes via FastAPI TestClient."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        """Point memory to a temp db and enable memory."""
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = str(Path(self.tmpdir.name) / "test_memory.sqlite3")

        monkeypatch.setenv("SPECTRUMCLAW_MEMORY_ENABLED", "true")
        monkeypatch.setenv("SPECTRUMCLAW_MEMORY_DB_PATH", db_path)

        # Clear config cache
        from backend.config import get_settings
        get_settings.cache_clear()

        from backend.app import create_app
        from fastapi.testclient import TestClient

        self.app = create_app()
        self.client = TestClient(self.app)
        yield
        self.tmpdir.cleanup()

    def test_overview_empty(self):
        resp = self.client.get("/api/memory/overview")
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is True
        assert data["thread_count"] == 0
        assert data["item_count"] == 0

    def test_items_empty(self):
        resp = self.client.get("/api/memory/items")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []

    def test_thread_not_found(self):
        resp = self.client.get("/api/memory/threads/nonexistent")
        assert resp.status_code == 404

    def test_record_feedback(self):
        resp = self.client.post("/api/memory/feedback", json={
            "target_type": "answer",
            "target_id": "evt_test",
            "rating": 4,
            "comment": "Good answer",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["feedback_id"].startswith("fb_")

    def test_overview_after_feedback(self):
        self.client.post("/api/memory/feedback", json={
            "target_type": "answer", "target_id": "evt_x", "rating": 3,
        })
        resp = self.client.get("/api/memory/overview")
        assert resp.status_code == 200
        data = resp.json()
        assert data["feedback_count"] == 1

    def test_items_with_filter(self):
        # write some items directly via store
        from backend.config import get_settings
        from backend.memory.store import MemoryStore

        settings = get_settings()
        store = MemoryStore(settings.memory_db_path)
        store.insert_item(type("Item", (), {
            "memory_id": "mem_a", "scope": "workspace", "kind": "episodic",
            "text": "RAG query about 2.4GHz", "summary": "Freq planning",
            "confidence": 0.9, "source_event_id": "", "thread_id": "th1",
            "skill_name": "freq", "tags_json": '["rag","itu"]',
            "valid_from": "2026-01-01T00:00:00", "valid_to": None,
            "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00",
        })())

        resp = self.client.get("/api/memory/items?kind=episodic")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["memory_id"] == "mem_a"

        resp = self.client.get("/api/memory/items?tag=itu")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 1

        resp = self.client.get("/api/memory/items?tag=nonexistent")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 0

    def test_thread_detail(self):
        from backend.config import get_settings
        from backend.memory.store import MemoryStore

        settings = get_settings()
        store = MemoryStore(settings.memory_db_path)
        store.upsert_thread(type("Thread", (), {
            "thread_id": "th_detail", "title": "Test", "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00", "summary": "summary", "turn_count": 5,
        })())
        store.insert_event(type("Event", (), {
            "event_id": "evt_detail", "thread_id": "th_detail", "event_type": "user",
            "role": "user", "content": "hello", "metadata_json": "{}",
            "created_at": "2026-01-01T00:00:00",
        })())

        resp = self.client.get("/api/memory/threads/th_detail")
        assert resp.status_code == 200
        data = resp.json()
        assert data["thread"]["thread_id"] == "th_detail"
        assert data["thread"]["turn_count"] == 5
        assert len(data["events"]) == 1

    def test_skill_runs(self):
        from backend.config import get_settings
        from backend.memory.store import MemoryStore

        settings = get_settings()
        store = MemoryStore(settings.memory_db_path)
        store.insert_skill_run(type("Run", (), {
            "run_id": "run1", "thread_id": "th1", "skill_name": "fp",
            "input_json": "{}", "output_summary": "done", "status": "success",
            "latency_ms": 100, "error": "", "rag_refs_json": "[]",
            "created_at": "2026-01-01T00:00:00",
        })())

        resp = self.client.get("/api/memory/skill-runs")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["runs"]) == 1

    def test_reports(self):
        from backend.config import get_settings
        from backend.memory.store import MemoryStore

        settings = get_settings()
        store = MemoryStore(settings.memory_db_path)
        store.insert_report(type("Report", (), {
            "report_id": "rpt1", "period": "2026-W22", "summary": "Weekly",
            "metrics_json": "{}", "suggestions_json": "[]", "status": "pending",
            "created_at": "2026-01-01T00:00:00",
        })())

        resp = self.client.get("/api/memory/reports")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["reports"]) == 1


class TestMemoryDisabled:
    """Verify settings.memory_enabled=False reflects in overview."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = str(Path(self.tmpdir.name) / "test_memory_off.sqlite3")

        monkeypatch.setenv("SPECTRUMCLAW_MEMORY_ENABLED", "false")
        monkeypatch.setenv("SPECTRUMCLAW_MEMORY_DB_PATH", db_path)

        from backend.config import get_settings
        get_settings.cache_clear()

        from backend.app import create_app
        from fastapi.testclient import TestClient

        self.app = create_app()
        self.client = TestClient(self.app)
        yield
        self.tmpdir.cleanup()

    def test_overview_shows_disabled(self):
        resp = self.client.get("/api/memory/overview")
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is False
