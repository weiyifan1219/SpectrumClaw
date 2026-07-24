"""Contract and safety-policy tests for UAV agent mission plans."""

from __future__ import annotations

import time

import pytest
from pydantic import ValidationError


def _runtime(*, state: str = "running", manual: bool = False) -> dict:
    return {
        "runtime": {
            "state": state,
            "manual": {"enabled": manual},
            "agent_navigation": {"ready": True},
        },
        "scene": {"vehicle": {"world": "urban_block"}},
    }


def test_mission_plan_rejects_raw_coordinates_and_velocity_fields():
    from backend.skills.uav_spectrum_sim.contracts import MissionPlan

    with pytest.raises(ValidationError):
        MissionPlan.model_validate({
            "mission_id": "plan-1",
            "template": "inspect_safe_perimeter",
            "expires_at": time.time() + 60,
            "target_enu_m": [10, 10, 10],
        })

    with pytest.raises(ValidationError):
        MissionPlan.model_validate({
            "mission_id": "plan-2",
            "template": "inspect_safe_perimeter",
            "expires_at": time.time() + 60,
            "velocity_mps": 2.5,
        })


def test_policy_rejects_expired_plan_before_any_flight_action():
    from backend.skills.uav_spectrum_sim.contracts import MissionPlan
    from backend.skills.uav_spectrum_sim.policy import MissionPolicy

    plan = MissionPlan(
        mission_id="expired-plan",
        template="inspect_safe_perimeter",
        expires_at=time.time() - 1,
    )

    result = MissionPolicy().validate(plan, _runtime())

    assert result.allowed is False
    assert result.code == "plan_expired"


def test_policy_refuses_plan_while_browser_has_manual_control():
    from backend.skills.uav_spectrum_sim.contracts import MissionPlan
    from backend.skills.uav_spectrum_sim.policy import MissionPolicy

    plan = MissionPlan(
        mission_id="manual-plan",
        template="collect_camera_evidence",
        landmark="north_gate",
        expires_at=time.time() + 60,
    )

    result = MissionPolicy().validate(plan, _runtime(manual=True))

    assert result.allowed is False
    assert result.code == "manual_control_active"


def test_audit_event_exposes_a_displayable_summary_not_hidden_thought():
    from backend.skills.uav_spectrum_sim.audit import AuditEvent

    event = AuditEvent(
        event_type="policy_decision",
        summary="任务位于安全周界内，等待用户批准。",
        data={"template": "inspect_safe_perimeter"},
    )

    payload = event.to_public_dict()

    assert payload["event_type"] == "policy_decision"
    assert payload["summary"] == "任务位于安全周界内，等待用户批准。"
    assert "thought" not in payload
    assert "reasoning" not in payload


def test_service_records_policy_decision_before_rejecting_expired_plan():
    from backend.skills.uav_spectrum_sim.contracts import MissionPlan
    from backend.skills.uav_spectrum_sim.mission import UavMissionService

    service = UavMissionService(status_reader=lambda: _runtime())
    result = service.execute_plan(MissionPlan(
        mission_id="expired-service-plan",
        template="inspect_safe_perimeter",
        expires_at=time.time() - 1,
    ))

    assert result["ok"] is False
    assert result["error_code"] == "plan_expired"
    assert result["events"][-1]["event_type"] == "policy_decision"
