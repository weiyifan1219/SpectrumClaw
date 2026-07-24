"""Safety and adapter contracts for the UAV mission service."""

from __future__ import annotations


def _status(
    *, state: str = "running", manual_enabled: bool = False,
    agent_navigation_ready: bool | None = None,
    east_m: float = 0.0, north_m: float = 0.0, altitude: float = 0.0,
):
    runtime = {
        "state": state,
        "manual": {"enabled": manual_enabled, "bridge_running": True},
        "camera": {"vehicle": {"position_m": [east_m, north_m, altitude]}},
    }
    if agent_navigation_ready is not None:
        runtime["agent_navigation"] = {"ready": agent_navigation_ready}
    return {
        "runtime": runtime,
        "scene": {"vehicle": {"world": "urban_block"}},
    }


def test_mission_requires_a_running_simulator():
    from backend.skills.uav_spectrum_sim.mission import UavMissionService

    service = UavMissionService(status_reader=lambda: _status(state="stopped"))

    result = service.execute("takeoff_and_hover", altitude_m=3)

    assert result["ok"] is False
    assert result["error_code"] == "simulator_not_running"


def test_takeoff_and_hover_uses_only_allowlisted_px4_actions():
    from backend.skills.uav_spectrum_sim.mission import UavMissionService

    statuses = iter([_status(altitude=0.0), _status(altitude=2.9), _status(altitude=2.9)])
    calls: list[tuple[str, float | None]] = []

    service = UavMissionService(
        status_reader=lambda: next(statuses),
        command_executor=lambda action, altitude_m=None: calls.append((action, altitude_m)) or {"ok": True, "action": action},
        sleep=lambda _: None,
        poll_interval_s=0,
    )

    result = service.execute("takeoff_and_hover", altitude_m=3)

    assert result["ok"] is True
    assert result["mission"] == "takeoff_and_hover"
    assert result["phase"] == "completed"
    assert calls == [("takeoff", 3.0), ("hover", None)]


def test_mission_refuses_to_preempt_active_manual_control():
    from backend.skills.uav_spectrum_sim.mission import UavMissionService

    service = UavMissionService(status_reader=lambda: _status(manual_enabled=True))

    result = service.execute("land")

    assert result["ok"] is False
    assert result["error_code"] == "manual_control_active"


def test_cancel_mission_falls_back_to_hover():
    from backend.skills.uav_spectrum_sim.mission import UavMissionService

    calls: list[str] = []
    service = UavMissionService(
        status_reader=lambda: _status(),
        command_executor=lambda action, altitude_m=None: calls.append(action) or {"ok": True},
        navigation_clearer=lambda: {"ok": True},
    )

    result = service.cancel()

    assert result["ok"] is True
    assert calls == ["hover"]


def test_manual_takeover_during_takeoff_preempts_before_hover():
    from backend.skills.uav_spectrum_sim.mission import UavMissionService

    statuses = iter([_status(altitude=0.0), _status(manual_enabled=True, altitude=1.5)])
    calls: list[str] = []
    service = UavMissionService(
        status_reader=lambda: next(statuses),
        command_executor=lambda action, altitude_m=None: calls.append(action) or {"ok": True},
        sleep=lambda _: None,
        poll_interval_s=0,
    )

    result = service.execute("takeoff_and_hover", altitude_m=3)

    assert result["ok"] is False
    assert result["error_code"] == "manual_control_preempted"
    assert calls == ["takeoff"]


def test_safe_landmark_navigation_uses_fixed_safe_target_only():
    from backend.skills.uav_spectrum_sim.mission import UavMissionService

    statuses = iter([
        _status(altitude=0.0),
        _status(altitude=19.8),
        _status(north_m=29.2, altitude=20.0),
        _status(north_m=29.2, altitude=20.0),
    ])
    commands: list[tuple[str, float | None]] = []
    targets: list[list[float]] = []
    clears: list[str] = []
    service = UavMissionService(
        status_reader=lambda: next(statuses),
        command_executor=lambda action, altitude_m=None: commands.append((action, altitude_m)) or {"ok": True},
        navigation_writer=lambda target: targets.append(target) or {"ok": True},
        navigation_clearer=lambda: clears.append("clear") or {"ok": True},
        sleep=lambda _: None,
        poll_interval_s=0,
    )

    result = service.execute("navigate_to_safe_landmark", landmark="north_gate")

    assert result["ok"] is True
    assert commands == [("takeoff", 20.0), ("hover", None)]
    assert targets == [[0.0, 30.0, 20.0]]
    assert result["target_enu_m"] == [0.0, 30.0, 20.0]
    assert result["phase"] == "completed_hovering"
    assert result["terminal_action"] == "hover"
    assert clears == ["clear"]


def test_navigation_rejects_unknown_landmark_without_sending_px4_command():
    from backend.skills.uav_spectrum_sim.mission import UavMissionService

    calls: list[str] = []
    service = UavMissionService(
        status_reader=lambda: _status(),
        command_executor=lambda action, altitude_m=None: calls.append(action) or {"ok": True},
    )

    result = service.execute("navigate_to_safe_landmark", landmark="office_east")

    assert result["ok"] is False
    assert result["error_code"] == "unknown_landmark"
    assert calls == []


def test_navigation_requires_a_running_agent_navigation_bridge():
    from backend.skills.uav_spectrum_sim.mission import UavMissionService

    calls: list[str] = []
    service = UavMissionService(
        status_reader=lambda: _status(agent_navigation_ready=False),
        command_executor=lambda action, altitude_m=None: calls.append(action) or {"ok": True},
    )

    result = service.execute("navigate_to_safe_landmark", landmark="north_gate")

    assert result["ok"] is False
    assert result["error_code"] == "agent_navigation_bridge_not_ready"
    assert calls == []


def test_perimeter_patrol_is_a_fixed_high_altitude_route():
    from backend.skills.uav_spectrum_sim.mission import SAFE_PERIMETER_ROUTE, UavMissionService

    statuses = [_status(altitude=0.0), _status(altitude=19.8)]
    statuses.extend(_status(east_m=point[0], north_m=point[1], altitude=point[2]) for point in SAFE_PERIMETER_ROUTE)
    statuses.append(_status(east_m=0.0, north_m=0.0, altitude=20.0))
    cursor = iter(statuses)
    targets: list[list[float]] = []
    commands: list[str] = []
    clears: list[str] = []
    service = UavMissionService(
        status_reader=lambda: next(cursor),
        command_executor=lambda action, altitude_m=None: commands.append(action) or {"ok": True},
        navigation_writer=lambda target: targets.append(target) or {"ok": True},
        navigation_clearer=lambda: clears.append("clear") or {"ok": True},
        sleep=lambda _: None,
        poll_interval_s=0,
    )

    result = service.execute("survey_safe_perimeter")

    assert result["ok"] is True
    assert targets == [list(point) for point in SAFE_PERIMETER_ROUTE]
    assert commands == ["takeoff", "hover"]
    assert clears == ["clear"]
    assert result["phase"] == "completed_hovering"


def test_manual_takeover_during_navigation_clears_agent_target_without_hover():
    from backend.skills.uav_spectrum_sim.mission import UavMissionService

    statuses = iter([_status(altitude=0.0), _status(altitude=19.8), _status(manual_enabled=True, altitude=20.0)])
    events: list[str] = []
    service = UavMissionService(
        status_reader=lambda: next(statuses),
        command_executor=lambda action, altitude_m=None: events.append(action) or {"ok": True},
        navigation_writer=lambda target: events.append("target") or {"ok": True},
        navigation_clearer=lambda: events.append("clear") or {"ok": True},
        sleep=lambda _: None,
        poll_interval_s=0,
    )

    result = service.execute("navigate_to_safe_landmark", landmark="north_gate")

    assert result["ok"] is False
    assert result["error_code"] == "manual_control_preempted"
    assert events == ["takeoff", "target", "clear"]
