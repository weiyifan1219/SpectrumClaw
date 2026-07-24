"""High-level, simulator-only UAV mission adapter.

Every caller (the built-in agent, HTTP UI, or an MCP client) enters through
this service.  The only component that owns MAVLink is the persistent control
bridge; callers can request only named missions and never raw flight packets.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from .audit import AuditEvent
from .contracts import MissionPlan
from .policy import MissionPolicy
from .templates import compile_template
from .runtime import (
    clear_agent_navigation_target,
    execute_vehicle_command,
    get_runtime_status,
    write_agent_navigation_target,
)


CRUISE_ALTITUDE_M = 20.0
MISSION_ACTIONS = (
    "takeoff_and_hover",
    "hover",
    "land",
    "return_to_launch",
    "navigate_to_safe_landmark",
    "survey_safe_perimeter",
)

# These targets are deliberately outside the building footprint.  Every
# navigation task climbs from the open spawn square to 20 m first; the fixed
# route then remains clear of all urban_block obstacles (highest roof: 22 m is
# never crossed horizontally).
SAFE_LANDMARKS: dict[str, tuple[float, float, float]] = {
    "north_gate": (0.0, 30.0, CRUISE_ALTITUDE_M),
    "south_gate": (0.0, -30.0, CRUISE_ALTITUDE_M),
    "east_gate": (30.0, 0.0, CRUISE_ALTITUDE_M),
    "west_gate": (-30.0, 0.0, CRUISE_ALTITUDE_M),
}
SAFE_PERIMETER_ROUTE: tuple[tuple[float, float, float], ...] = (
    (0.0, -30.0, CRUISE_ALTITUDE_M),
    (-30.0, -30.0, CRUISE_ALTITUDE_M),
    (30.0, -30.0, CRUISE_ALTITUDE_M),
    (30.0, 30.0, CRUISE_ALTITUDE_M),
    (-30.0, 30.0, CRUISE_ALTITUDE_M),
    (0.0, 30.0, CRUISE_ALTITUDE_M),
    (0.0, 0.0, CRUISE_ALTITUDE_M),
)


class UavMissionService:
    """Run bounded mission intents against the current PX4/Gazebo simulation."""

    def __init__(
        self,
        *,
        status_reader: Callable[[], dict[str, Any]] = get_runtime_status,
        command_executor: Callable[[str, float | None], dict[str, Any]] = execute_vehicle_command,
        navigation_writer: Callable[[list[float]], dict[str, Any]] = write_agent_navigation_target,
        navigation_clearer: Callable[[], dict[str, Any]] = clear_agent_navigation_target,
        policy: MissionPolicy | None = None,
        sleep: Callable[[float], None] = time.sleep,
        poll_interval_s: float = 0.25,
        arrival_timeout_s: float = 35.0,
    ) -> None:
        self._status_reader = status_reader
        self._command_executor = command_executor
        self._navigation_writer = navigation_writer
        self._navigation_clearer = navigation_clearer
        self._sleep = sleep
        self._poll_interval_s = poll_interval_s
        self._arrival_timeout_s = arrival_timeout_s
        self._policy = policy or MissionPolicy()
        self._lock = threading.RLock()
        self._last_mission: dict[str, Any] = {"phase": "idle", "mission": None, "updated_at": None}
        self._events: list[AuditEvent] = []

    def _event(self, event_type: str, summary: str, **data: Any) -> dict[str, Any]:
        event = AuditEvent(event_type=event_type, summary=summary, data=data)
        self._events.append(event)
        self._events = self._events[-120:]
        return event.to_public_dict()

    def recent_events(self) -> list[dict[str, Any]]:
        """Return displayable execution evidence, never hidden model reasoning."""
        return [event.to_public_dict() for event in self._events]

    @staticmethod
    def _vehicle(status: dict[str, Any]) -> dict[str, Any]:
        runtime = status.get("runtime", {}) if isinstance(status, dict) else {}
        camera = runtime.get("camera", {}) if isinstance(runtime, dict) else {}
        vehicle = camera.get("vehicle", {}) if isinstance(camera, dict) else {}
        return vehicle if isinstance(vehicle, dict) else {}

    @classmethod
    def _position_enu_m(cls, status: dict[str, Any]) -> tuple[float, float, float] | None:
        position = cls._vehicle(status).get("position_m")
        if not isinstance(position, list) or len(position) < 3:
            return None
        try:
            return float(position[0]), float(position[1]), float(position[2])
        except (TypeError, ValueError):
            return None

    @classmethod
    def _altitude_m(cls, status: dict[str, Any]) -> float | None:
        position = cls._position_enu_m(status)
        return position[2] if position else None

    def _record(self, mission: str | None, phase: str, **details: Any) -> dict[str, Any]:
        self._last_mission = {"mission": mission, "phase": phase, "updated_at": time.time(), **details}
        return dict(self._last_mission)

    @staticmethod
    def _manual_active(status: dict[str, Any]) -> bool:
        return bool(status.get("runtime", {}).get("manual", {}).get("enabled"))

    def inspect(self) -> dict[str, Any]:
        """Return current real simulator state and the service's task contract."""
        status = self._status_reader()
        return {
            "ok": True,
            "simulation": {
                "state": status.get("runtime", {}).get("state", "unknown"),
                "manual_control": self._manual_active(status),
                "vehicle": self._vehicle(status),
            },
            "last_mission": dict(self._last_mission),
            "allowed_missions": list(MISSION_ACTIONS),
            "safe_landmarks": {name: list(target) for name, target in SAFE_LANDMARKS.items()},
            "safety": {
                "navigation_altitude_m": CRUISE_ALTITUDE_M,
                "raw_coordinates": "not exposed",
                "manual_control_priority": True,
            },
        }

    def _preflight(self, mission: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        if mission not in MISSION_ACTIONS:
            return None, {"ok": False, "error_code": "unknown_mission", "message": f"不支持的仿真任务：{mission}"}
        status = self._status_reader()
        runtime = status.get("runtime", {}) if isinstance(status, dict) else {}
        if runtime.get("state") != "running":
            return None, {"ok": False, "error_code": "simulator_not_running", "message": "请先启动 PX4/Gazebo 仿真"}
        if self._manual_active(status):
            return None, {
                "ok": False,
                "error_code": "manual_control_active",
                "message": "网页遥控正在接管飞行器；请先释放手动控制后再交给智能体",
            }
        if mission in {"navigate_to_safe_landmark", "survey_safe_perimeter"}:
            agent_navigation = runtime.get("agent_navigation")
            # The default keeps dependency-injected unit tests independent from
            # the runtime process record.  A real runtime always supplies it.
            if isinstance(agent_navigation, dict) and not bool(agent_navigation.get("ready")):
                return None, {
                    "ok": False,
                    "error_code": "agent_navigation_bridge_not_ready",
                    "message": "当前 PX4 控制桥尚未加载智能体定点导航能力；请在无人机安全落地后重启仿真",
                }
        return status, None

    def _wait_for_altitude(self, altitude_m: float) -> str:
        deadline = time.monotonic() + self._arrival_timeout_s
        tolerance_m = max(0.35, altitude_m * 0.12)
        while time.monotonic() <= deadline:
            status = self._status_reader()
            if self._manual_active(status):
                return "manual_control_preempted"
            current = self._altitude_m(status)
            if current is not None and current >= altitude_m - tolerance_m:
                return "arrived"
            self._sleep(self._poll_interval_s)
        return "timeout"

    def _wait_for_position(self, target: tuple[float, float, float]) -> str:
        deadline = time.monotonic() + self._arrival_timeout_s
        while time.monotonic() <= deadline:
            status = self._status_reader()
            if self._manual_active(status):
                return "manual_control_preempted"
            current = self._position_enu_m(status)
            if current is not None:
                horizontal = ((current[0] - target[0]) ** 2 + (current[1] - target[1]) ** 2) ** 0.5
                if horizontal <= 1.5 and abs(current[2] - target[2]) <= 1.5:
                    return "arrived"
            self._sleep(self._poll_interval_s)
        return "timeout"

    def _takeoff_to_cruise(self, mission: str) -> dict[str, Any] | None:
        self._record(mission, "taking_off", target_altitude_m=CRUISE_ALTITUDE_M)
        try:
            self._command_executor("takeoff", CRUISE_ALTITUDE_M)
        except (RuntimeError, ValueError) as exc:
            return {"ok": False, "error_code": "px4_command_failed", "message": str(exc)}
        arrival = self._wait_for_altitude(CRUISE_ALTITUDE_M)
        if arrival == "manual_control_preempted":
            return {"ok": False, "error_code": "manual_control_preempted", "message": "网页遥控已接管；智能体任务已停止"}
        if arrival != "arrived":
            return {"ok": False, "error_code": "takeoff_timeout", "message": "未能安全到达巡航高度，未进入导航"}
        return None

    def _abort_navigation(self, mission: str, reason: str) -> dict[str, Any]:
        self._navigation_clearer()
        if reason == "manual_control_preempted":
            self._record(mission, "preempted_by_manual_control")
            return {"ok": False, "error_code": reason, "message": "网页遥控已接管；智能体任务已停止，不再发送后续飞控命令"}
        try:
            self._command_executor("hover", None)
        except (RuntimeError, ValueError):
            pass
        self._record(mission, "timeout")
        return {"ok": False, "error_code": "navigation_timeout", "message": "未到达安全航点；已清除目标并请求悬停"}

    def _navigate(self, mission: str, targets: tuple[tuple[float, float, float], ...]) -> dict[str, Any]:
        takeoff_error = self._takeoff_to_cruise(mission)
        if takeoff_error:
            return takeoff_error
        for index, target in enumerate(targets, start=1):
            self._record(mission, "navigating", waypoint_index=index, waypoint_count=len(targets), target_enu_m=list(target))
            try:
                self._navigation_writer(list(target))
            except (RuntimeError, ValueError) as exc:
                return self._abort_navigation(mission, "navigation_writer_failed") | {"detail": str(exc)}
            arrival = self._wait_for_position(target)
            if arrival != "arrived":
                return self._abort_navigation(mission, arrival)
        # A completed route must have a visible, safe terminal action.  Leaving
        # the last position setpoint to expire made a mission look unfinished
        # in the UI and gave PX4 no explicit hand-off state.
        self._navigation_clearer()
        try:
            self._command_executor("hover", None)
        except (RuntimeError, ValueError) as exc:
            self._record(mission, "terminal_hover_failed", target_enu_m=list(targets[-1]))
            return {
                "ok": False,
                "error_code": "terminal_hover_failed",
                "message": f"已抵达最终安全航点，但未能确认悬停：{exc}",
            }
        state = self._record(mission, "completed_hovering", target_enu_m=list(targets[-1]), terminal_action="hover")
        return {
            "ok": True,
            "mission": mission,
            **state,
            "message": "任务已成功完成，已清除导航目标并在安全终点悬停。",
            "vehicle": self._vehicle(self._status_reader()),
        }

    def execute(self, mission: str, altitude_m: float | None = None, landmark: str | None = None) -> dict[str, Any]:
        """Execute a named task with manual-control exclusion and feedback."""
        with self._lock:
            _, error = self._preflight(mission)
            if error:
                return error
            if mission == "navigate_to_safe_landmark":
                target = SAFE_LANDMARKS.get(str(landmark or ""))
                if target is None:
                    return {
                        "ok": False,
                        "error_code": "unknown_landmark",
                        "message": "仅允许 north_gate、south_gate、east_gate、west_gate 四个安全航点",
                    }
                return self._navigate(mission, (target,))
            if mission == "survey_safe_perimeter":
                return self._navigate(mission, SAFE_PERIMETER_ROUTE)
            if mission == "takeoff_and_hover":
                target = 3.0 if altitude_m is None else float(altitude_m)
                if not 1.0 <= target <= 20.0:
                    return {"ok": False, "error_code": "invalid_altitude", "message": "起飞高度必须在 1 到 20 米之间"}
                self._record(mission, "taking_off", target_altitude_m=target)
                try:
                    self._command_executor("takeoff", target)
                except (RuntimeError, ValueError) as exc:
                    return {"ok": False, "error_code": "px4_command_failed", "message": str(exc)}
                arrival = self._wait_for_altitude(target)
                if arrival == "manual_control_preempted":
                    self._record(mission, "preempted_by_manual_control", target_altitude_m=target)
                    return {"ok": False, "error_code": "manual_control_preempted", "message": "网页遥控已接管；智能体任务已停止，不再发送后续飞控命令", "mission": mission}
                if arrival != "arrived":
                    self._record(mission, "timeout", target_altitude_m=target)
                    return {"ok": False, "error_code": "takeoff_timeout", "message": "PX4 未在限定时间内到达目标高度，未继续执行后续任务", "mission": mission}
                try:
                    self._command_executor("hover", None)
                except (RuntimeError, ValueError) as exc:
                    return {"ok": False, "error_code": "px4_command_failed", "message": str(exc)}
                state = self._record(mission, "completed", target_altitude_m=target)
            else:
                if mission in {"hover", "land", "return_to_launch"}:
                    self._navigation_clearer()
                action = "return_to_launch" if mission == "return_to_launch" else mission
                self._record(mission, "executing")
                try:
                    self._command_executor(action, None)
                except (RuntimeError, ValueError) as exc:
                    return {"ok": False, "error_code": "px4_command_failed", "message": str(exc)}
                state = self._record(mission, "completed")
            return {"ok": True, "mission": mission, **state, "vehicle": self._vehicle(self._status_reader())}

    def execute_plan(self, plan: MissionPlan) -> dict[str, Any]:
        """Apply policy first, then map a declarative plan to an existing task.

        The current mapping deliberately stops at the task service; no plan can
        introduce raw movement commands or a second MAVLink control path.
        """
        with self._lock:
            self._event("intent", "收到受限无人机任务计划。", mission_id=plan.mission_id, template=plan.template)
            decision = self._policy.validate(plan, self._status_reader())
            self._event("policy_decision", decision.summary, allowed=decision.allowed, code=decision.code)
            if not decision.allowed:
                return {
                    "ok": False,
                    "error_code": decision.code,
                    "message": decision.summary,
                    "events": self.recent_events(),
                }
            simple_missions = {"takeoff_and_hover", "hover", "land", "return_to_launch"}
            if plan.template in simple_missions:
                mission = plan.template
                landmark = plan.landmark
                evidence: list[str] = []
            else:
                compiled = compile_template(plan.template, landmark=plan.landmark)
                mission = compiled.mission
                landmark = compiled.landmark
                evidence = compiled.evidence
            self._event("tool_call", "请求受限飞行任务。", mission=mission)
            result = self.execute(mission, plan.altitude_m, landmark)
            self._event(
                "completion" if result.get("ok") else "error",
                "飞行任务已完成。" if result.get("ok") else str(result.get("message", "飞行任务失败。")),
                mission=mission,
                ok=bool(result.get("ok")),
            )
            return {**result, "plan": plan.model_dump(), "requested_evidence": evidence, "events": self.recent_events()}

    def cancel(self) -> dict[str, Any]:
        """Stop a task by clearing the target before the bounded PX4 hover action."""
        with self._lock:
            status = self._status_reader()
            if status.get("runtime", {}).get("state") != "running":
                return {"ok": False, "error_code": "simulator_not_running", "message": "PX4/Gazebo 仿真未运行"}
            self._navigation_clearer()
            try:
                self._command_executor("hover", None)
            except (RuntimeError, ValueError) as exc:
                return {"ok": False, "error_code": "px4_command_failed", "message": str(exc)}
            state = self._record(self._last_mission.get("mission"), "cancelled")
            return {"ok": True, **state}


_service: UavMissionService | None = None


def get_uav_mission_service() -> UavMissionService:
    """Return the process-wide adapter shared by native tools and MCP."""
    global _service
    if _service is None:
        _service = UavMissionService()
    return _service
