"""End-to-end safety contracts for the UAV task agent (no live PX4 required)."""

from __future__ import annotations

import time

import pytest


def _status(*, manual: bool = False, navigation_ready: bool = True) -> dict:
    return {
        "runtime": {
            "state": "running",
            "manual": {"enabled": manual},
            "agent_navigation": {"ready": navigation_ready},
        },
    }


def _orchestrator(tmp_path, *, result: dict):
    from backend.agents.uav_operations.orchestrator import UavOperationsOrchestrator
    from backend.skills.uav_spectrum_sim.contracts import MissionPlan

    class Service:
        _status_reader = staticmethod(_status)

        def __init__(self):
            self.calls: list[str] = []

        def execute_plan(self, plan):
            self.calls.append(plan.template)
            return result

        def cancel(self):
            return {"ok": True}

    class Author:
        def author(self, run_id, intent):
            return (
                MissionPlan(
                    mission_id=run_id,
                    template="inspect_safe_perimeter",
                    expires_at=time.time() + 120,
                ),
                {"provider": "test_safe_compiler", "accepted": True},
            )

    service = Service()
    orchestrator = UavOperationsOrchestrator(service=service, sandbox_root=tmp_path)
    orchestrator._author = Author()
    return orchestrator, service


def test_natural_language_draft_approval_and_terminal_summary_are_correlated(tmp_path):
    orchestrator, service = _orchestrator(
        tmp_path,
        result={
            "ok": True,
            "terminal_action": "hover",
            "message": "巡检完成，已清除导航目标并在安全终点悬停。",
            "events": [{"event_type": "completion", "summary": "适配层完成任务。", "data": {"ok": True}}],
        },
    )

    draft = orchestrator.create_draft("巡检安全周界后返回")
    completed = orchestrator.approve(draft["run_id"], draft["plan_digest"])

    assert draft["status"] == "awaiting_approval"
    assert service.calls == ["inspect_safe_perimeter"]
    assert completed["status"] == "completed"
    assert completed["lifecycle"] == {"phase": "completed", "terminal": True, "reason": None, "terminal_action": "hover"}
    assert completed["started_at"] is not None and completed["ended_at"] is not None
    assert {event["event_type"] for event in completed["events"]} >= {"intent", "policy_decision", "run_started", "completion"}
    assert all(event["run_id"] == draft["run_id"] for event in completed["events"])
    assert all(event["trace_id"] == draft["trace_id"] for event in completed["events"])


def test_manual_takeover_or_timeout_becomes_terminal_failure_without_followup_commands(tmp_path):
    orchestrator, service = _orchestrator(
        tmp_path,
        result={
            "ok": False,
            "error_code": "manual_control_preempted",
            "message": "检测到 WASD 人工接管，已清除导航目标且未再发送飞控指令。",
            "events": [{"event_type": "interruption", "summary": "人工接管。", "data": {"reason": "manual_control_preempted"}}],
        },
    )

    draft = orchestrator.create_draft("巡检安全周界")
    failed = orchestrator.approve(draft["run_id"], draft["plan_digest"])

    assert service.calls == ["inspect_safe_perimeter"]
    assert failed["status"] == "failed"
    assert failed["error_code"] == "manual_control_preempted"
    assert failed["lifecycle"]["terminal"] is True
    assert failed["lifecycle"]["reason"] == "manual_control_preempted"


def test_sandbox_rejects_executable_artifact_before_any_flight_execution(tmp_path):
    from backend.agents.uav_operations.sandbox import MissionSandbox

    sandbox = MissionSandbox(tmp_path)
    with pytest.raises(ValueError, match="不允许"):
        sandbox.write_text("uav_safe_001", "unreviewed.py", "import mavsdk")
    assert not (tmp_path / "uav_safe_001" / "unreviewed.py").exists()


def test_native_and_mcp_entrypoints_build_the_same_plan_and_policy_surface():
    from backend.skills.uav_spectrum_sim.contracts import build_mission_plan
    from backend.skills.uav_spectrum_sim.policy import MissionPolicy
    from backend.tools.registry import _build_uav_plan

    native = _build_uav_plan("native_001", "collect_camera_evidence", "north_gate", 20, 120)
    # MCP's private _plan delegates to this SDK-independent common factory;
    # testing it here keeps the contract verifiable when MCP is optional.
    mcp = build_mission_plan("mcp_001", "collect_camera_evidence", "north_gate", 20, 120)

    assert set(native.model_dump()) == set(mcp.model_dump())
    assert native.template == mcp.template == "collect_camera_evidence"
    assert native.landmark == mcp.landmark == "north_gate"
    policy = MissionPolicy()
    assert policy.validate(native, _status()).allowed is True
    assert policy.validate(mcp, _status()).allowed is True
