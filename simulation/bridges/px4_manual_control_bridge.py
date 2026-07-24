#!/usr/bin/env python3
"""Persistent, simulation-only PX4 Offboard bridge for browser manual control.

The browser never sends MAVLink packets. It only updates a small state file
through the FastAPI allow-list. This process owns the 50 Hz MAVLink stream,
which is required by PX4 for Offboard mode, and turns stale input into a zero
body-frame velocity command so releasing a key results in a hover.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import tempfile
import time
from pathlib import Path
from typing import Any

from pymavlink import mavutil


MAVLINK_BIND = "udpin:0.0.0.0:14540"
SETPOINT_HZ = 50.0
INPUT_TIMEOUT_S = 0.45
MAX_HORIZONTAL_SPEED_MPS = 1.2
MAX_VERTICAL_SPEED_MPS = 0.8
MAX_YAW_RATE_RADPS = 0.9
OFFBOARD_CUSTOM_MAIN_MODE = 6


def clamp(value: Any, lower: float = -1.0, upper: float = 1.0) -> float:
    try:
        return max(lower, min(upper, float(value)))
    except (TypeError, ValueError):
        return 0.0


class ManualControlBridge:
    def __init__(self, state_path: Path, agent_state_path: Path, status_path: Path) -> None:
        self.state_path = state_path
        self.agent_state_path = agent_state_path
        self.status_path = status_path
        self.running = True
        self.master: Any | None = None
        self.target_system = 1
        self.target_component = 1
        self.offboard_requested = False
        self.offboard_acknowledged = False
        self.armed = False
        self.flight_mode = "unknown"
        self.offboard_active = False
        self.last_error = ""
        self.last_state: dict[str, Any] = {}

    @staticmethod
    def _load_json(path: Path) -> dict[str, Any]:
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
            return parsed if isinstance(parsed, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    def load_state(self) -> dict[str, Any]:
        return self._load_json(self.state_path)

    def load_agent_state(self) -> dict[str, Any]:
        return self._load_json(self.agent_state_path)

    def write_status(self, state: dict[str, Any], agent_state: dict[str, Any]) -> None:
        manual_lease_fresh = self.manual_active(state)
        payload = {
            "connected": self.master is not None,
            # ``enabled`` is the effective browser takeover, never merely a
            # stale flag left by a closed tab.  This same value gates agent
            # admission in the web API, so an expired lease cannot block the
            # agent indefinitely.
            "enabled": manual_lease_fresh,
            "lease_fresh": manual_lease_fresh,
            "requested": bool(state.get("enabled")),
            "offboard_requested": self.offboard_requested,
            "offboard_acknowledged": self.offboard_acknowledged,
            "armed": self.armed,
            "flight_mode": self.flight_mode,
            "offboard_active": self.offboard_active,
            "last_input_at": state.get("updated_at"),
            "last_error": self.last_error,
            "agent_navigation_active": self.agent_active(agent_state),
            "agent_target_enu_m": agent_state.get("target_enu_m") if self.agent_active(agent_state) else None,
            "updated_at": time.time(),
        }
        self.status_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", dir=self.status_path.parent, delete=False, encoding="utf-8") as handle:
            json.dump(payload, handle)
            temporary = Path(handle.name)
        os.replace(temporary, self.status_path)

    def connect(self) -> bool:
        try:
            master = mavutil.mavlink_connection(MAVLINK_BIND, source_system=248, source_component=191)
            heartbeat = master.wait_heartbeat(timeout=5)
            if heartbeat is None:
                raise RuntimeError("未收到 PX4 MAVLink 心跳")
            self.master = master
            self.target_system = int(heartbeat.get_srcSystem())
            self.target_component = int(heartbeat.get_srcComponent())
            self.last_error = ""
            return True
        except Exception as exc:
            self.master = None
            self.last_error = str(exc)
            return False

    def velocity_from_state(self, state: dict[str, Any]) -> tuple[float, float, float, float]:
        fresh = bool(state.get("enabled")) and (time.time() - float(state.get("updated_at") or 0) <= INPUT_TIMEOUT_S)
        if not fresh:
            return 0.0, 0.0, 0.0, 0.0
        # BODY_NED binds W/S and A/D to the aircraft's current heading, which
        # is also the heading of the physical chase camera.
        return (
            clamp(state.get("forward")) * MAX_HORIZONTAL_SPEED_MPS,
            clamp(state.get("right")) * MAX_HORIZONTAL_SPEED_MPS,
            -clamp(state.get("up")) * MAX_VERTICAL_SPEED_MPS,
            clamp(state.get("yaw")) * MAX_YAW_RATE_RADPS,
        )

    @staticmethod
    def manual_active(state: dict[str, Any]) -> bool:
        return bool(state.get("enabled")) and (time.time() - float(state.get("updated_at") or 0) <= INPUT_TIMEOUT_S)

    @staticmethod
    def agent_active(state: dict[str, Any]) -> bool:
        if not bool(state.get("enabled")) or time.time() > float(state.get("expires_at") or 0):
            return False
        target = state.get("target_enu_m")
        return isinstance(target, list) and len(target) == 3

    def send_manual_velocity_setpoint(self, state: dict[str, Any]) -> None:
        if self.master is None:
            return
        vx, vy, vz, yaw_rate = self.velocity_from_state(state)
        mask = (
            mavutil.mavlink.POSITION_TARGET_TYPEMASK_X_IGNORE
            | mavutil.mavlink.POSITION_TARGET_TYPEMASK_Y_IGNORE
            | mavutil.mavlink.POSITION_TARGET_TYPEMASK_Z_IGNORE
            | mavutil.mavlink.POSITION_TARGET_TYPEMASK_AX_IGNORE
            | mavutil.mavlink.POSITION_TARGET_TYPEMASK_AY_IGNORE
            | mavutil.mavlink.POSITION_TARGET_TYPEMASK_AZ_IGNORE
            | mavutil.mavlink.POSITION_TARGET_TYPEMASK_YAW_IGNORE
        )
        try:
            self.master.mav.set_position_target_local_ned_send(
                int(time.time() * 1000) & 0xFFFFFFFF,
                self.target_system,
                self.target_component,
                mavutil.mavlink.MAV_FRAME_BODY_NED,
                mask,
                0.0, 0.0, 0.0,
                vx, vy, vz,
                0.0, 0.0, 0.0,
                0.0, yaw_rate,
            )
        except OSError as exc:
            self.master = None
            self.last_error = str(exc)

    def send_agent_position_setpoint(self, state: dict[str, Any]) -> None:
        """Send a fixed local-NED position setpoint from a validated ENU target."""
        if self.master is None:
            return
        try:
            east, north, altitude = (float(value) for value in state["target_enu_m"])
            # Gazebo publishes ENU while PX4 local position targets use NED.
            # The agent channel has already been range-limited by runtime.py.
            mask = (
                mavutil.mavlink.POSITION_TARGET_TYPEMASK_VX_IGNORE
                | mavutil.mavlink.POSITION_TARGET_TYPEMASK_VY_IGNORE
                | mavutil.mavlink.POSITION_TARGET_TYPEMASK_VZ_IGNORE
                | mavutil.mavlink.POSITION_TARGET_TYPEMASK_AX_IGNORE
                | mavutil.mavlink.POSITION_TARGET_TYPEMASK_AY_IGNORE
                | mavutil.mavlink.POSITION_TARGET_TYPEMASK_AZ_IGNORE
                | mavutil.mavlink.POSITION_TARGET_TYPEMASK_YAW_IGNORE
                | mavutil.mavlink.POSITION_TARGET_TYPEMASK_YAW_RATE_IGNORE
            )
            self.master.mav.set_position_target_local_ned_send(
                int(time.time() * 1000) & 0xFFFFFFFF,
                self.target_system,
                self.target_component,
                mavutil.mavlink.MAV_FRAME_LOCAL_NED,
                mask,
                north, east, -altitude,
                0.0, 0.0, 0.0,
                0.0, 0.0, 0.0,
                0.0, 0.0,
            )
        except (OSError, TypeError, ValueError) as exc:
            self.master = None
            self.last_error = str(exc)

    def send_setpoint(self, manual_state: dict[str, Any], agent_state: dict[str, Any]) -> None:
        # A fresh browser command always wins over an agent task.  The service
        # detects that same takeover and clears the agent target immediately.
        if self.manual_active(manual_state):
            self.send_manual_velocity_setpoint(manual_state)
        elif self.agent_active(agent_state):
            self.send_agent_position_setpoint(agent_state)
        else:
            self.send_manual_velocity_setpoint({})

    def request_offboard(self) -> None:
        if self.master is None or self.offboard_requested:
            return
        self.master.mav.command_long_send(
            self.target_system,
            self.target_component,
            mavutil.mavlink.MAV_CMD_DO_SET_MODE,
            0,
            mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
            OFFBOARD_CUSTOM_MAIN_MODE,
            0.0, 0.0, 0.0, 0.0, 0.0,
        )
        self.offboard_requested = True

    def read_acknowledgements(self) -> None:
        if self.master is None:
            return
        while True:
            message = self.master.recv_match(blocking=False)
            if message is None:
                return
            if message.get_type() == "HEARTBEAT":
                self.armed = bool(int(message.base_mode) & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
                self.flight_mode = str(mavutil.mode_string_v10(message))
                self.offboard_active = self.flight_mode.strip().upper() == "OFFBOARD"
            if message.get_type() == "COMMAND_ACK" and int(message.command) == mavutil.mavlink.MAV_CMD_DO_SET_MODE:
                if int(message.result) == mavutil.mavlink.MAV_RESULT_ACCEPTED:
                    self.offboard_acknowledged = True
                else:
                    self.last_error = f"PX4 未接受 Offboard 模式切换（result={int(message.result)}）"
                    self.offboard_requested = False

    def run(self) -> None:
        interval = 1.0 / SETPOINT_HZ
        next_tick = time.monotonic()
        while self.running:
            state = self.load_state()
            agent_state = self.load_agent_state()
            self.last_state = state
            if self.master is None:
                self.connect()
                self.offboard_requested = False
                self.offboard_acknowledged = False
            if self.master is not None:
                self.send_setpoint(state, agent_state)
                if self.manual_active(state) or self.agent_active(agent_state):
                    self.request_offboard()
                else:
                    self.offboard_requested = False
                    self.offboard_acknowledged = False
                self.read_acknowledgements()
            self.write_status(state, agent_state)
            next_tick += interval
            time.sleep(max(0.0, next_tick - time.monotonic()))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--agent-state", required=True, type=Path)
    parser.add_argument("--status", required=True, type=Path)
    args = parser.parse_args()
    bridge = ManualControlBridge(args.state, args.agent_state, args.status)

    def stop(_signum, _frame):
        bridge.running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    bridge.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
