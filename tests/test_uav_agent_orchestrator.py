"""Behavior tests for the task-level UAV operations orchestrator."""

from __future__ import annotations

import threading
import time


def _status() -> dict:
    return {
        "runtime": {
            "state": "running",
            "manual": {"enabled": False},
            "agent_navigation": {"ready": True},
        },
    }


def test_orchestrator_creates_draft_without_executing_flight(tmp_path):
    from backend.agents.uav_operations.orchestrator import UavOperationsOrchestrator

    calls: list[str] = []

    class Service:
        _status_reader = staticmethod(_status)

        def execute_plan(self, plan):
            calls.append(plan.template)
            return {"ok": True, "events": []}

        def cancel(self):
            return {"ok": True}

    orchestrator = UavOperationsOrchestrator(service=Service(), sandbox_root=tmp_path)
    run = orchestrator.create_draft("巡检安全周界后返回")

    assert run["status"] == "awaiting_approval"
    assert run["plan"]["template"] == "inspect_safe_perimeter"
    assert calls == []


def test_orchestrator_executes_only_matching_approval_digest(tmp_path):
    from backend.agents.uav_operations.orchestrator import UavOperationsOrchestrator

    class Service:
        _status_reader = staticmethod(_status)

        def execute_plan(self, plan):
            return {"ok": True, "mission": "survey_safe_perimeter", "events": []}

        def cancel(self):
            return {"ok": True}

    orchestrator = UavOperationsOrchestrator(service=Service(), sandbox_root=tmp_path)
    run = orchestrator.create_draft("巡检安全周界后返回")
    rejected = orchestrator.approve(run["run_id"], "wrong-digest")
    approved = orchestrator.approve(run["run_id"], run["plan_digest"])

    assert rejected["status"] == "awaiting_approval"
    assert rejected["error_code"] == "plan_digest_mismatch"
    assert approved["status"] == "completed"
    assert approved["started_at"] is not None
    assert approved["ended_at"] is not None
    assert approved["lifecycle"] == {"phase": "completed", "terminal": True, "reason": None, "terminal_action": None}
    assert any(event["event_type"] == "run_started" for event in approved["events"])


def test_orchestrator_starts_approved_plan_in_background_for_event_streaming(tmp_path):
    from backend.agents.uav_operations.orchestrator import UavOperationsOrchestrator

    started = threading.Event()
    release = threading.Event()

    class Service:
        _status_reader = staticmethod(_status)

        def execute_plan(self, plan):
            started.set()
            release.wait(timeout=2)
            return {"ok": True, "events": []}

        def cancel(self):
            return {"ok": True}

    orchestrator = UavOperationsOrchestrator(service=Service(), sandbox_root=tmp_path)
    run = orchestrator.create_draft("巡检安全周界")
    pending = orchestrator.start_approval(run["run_id"], run["plan_digest"])

    assert pending["status"] == "running"
    assert started.wait(timeout=1)
    release.set()
    deadline = time.time() + 1
    while time.time() < deadline and orchestrator.get_run(run["run_id"])["status"] == "running":
        time.sleep(0.01)
    assert orchestrator.get_run(run["run_id"])["status"] == "completed"


def test_orchestrator_restores_running_task_as_interrupted_after_restart(tmp_path):
    from backend.agents.uav_operations.orchestrator import UavOperationsOrchestrator

    class Service:
        _status_reader = staticmethod(_status)

        def execute_plan(self, plan):
            return {"ok": True, "events": []}

        def cancel(self):
            return {"ok": True}

    first = UavOperationsOrchestrator(service=Service(), sandbox_root=tmp_path)
    run = first.create_draft("巡检安全周界")
    first._runs[run["run_id"]].update(status="running", lifecycle={"phase": "started", "terminal": False, "reason": None})
    first._persist(first._runs[run["run_id"]])

    restored = UavOperationsOrchestrator(service=Service(), sandbox_root=tmp_path).get_run(run["run_id"])

    assert restored["status"] == "interrupted"
    assert restored["lifecycle"]["terminal"] is True
    assert restored["lifecycle"]["reason"] == "orchestrator_restarted"
    assert any(event["event_type"] == "interruption" for event in restored["events"])
