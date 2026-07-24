"""Runtime control and inspection for the headless UAV spectrum simulator.

This module deliberately owns only the PX4/Gazebo process lifecycle.  It does
not contain an Agent loop, RF reconstruction, or Sionna scenario generation.
Those are later-stage responsibilities.  The API reports actual marker and
process state so the web UI never presents a fabricated simulator status.
"""

from __future__ import annotations

import json
import os
import secrets
import shlex
import signal
import shutil
import socket
import subprocess
import time
from pathlib import Path
from typing import Any


DEFAULT_RUNTIME_ROOT = Path("/workspace/YiFan/spectrumclaw_runtime")
DEFAULT_PROJECT_ROOT = Path("/workspace/YiFan/SpectrumClaw")
PHASE_NAME = "uav-spectrum-sim-phase1"
CAMERA_MODEL = "x500_lidar_2d_cam"
PX4_SIM_MODEL = f"gz_{CAMERA_MODEL}"
GAZEBO_WORLD = "urban_block"
CAMERA_DIRECTIONS = ("front", "rear", "left", "right", "down", "chase")
GAZEBO_GUI_DISPLAY = ":91"
GAZEBO_GUI_VNC_PORT = 5901
REQUIRED_STAGES = (
    "01_system",
    "02_px4",
    "03_sionna_rt",
    "04_ros_gazebo_px4_smoke",
    "05_sionna_rt_smoke",
    "06_versions",
    "07_debug_bridge",
)


def _runtime_root() -> Path:
    return Path(os.environ.get("SPECTRUMCLAW_UAV_RUNTIME_ROOT", DEFAULT_RUNTIME_ROOT))


def _project_root() -> Path:
    return Path(os.environ.get("SPECTRUMCLAW_UAV_PROJECT_ROOT", DEFAULT_PROJECT_ROOT))


def _state_dir() -> Path:
    return _runtime_root() / "install-state" / PHASE_NAME


def _log_dir() -> Path:
    return _runtime_root() / "logs" / PHASE_NAME


def _pid_file() -> Path:
    return _state_dir() / "px4_gazebo.runtime.json"


def _px4_dir() -> Path:
    configured = os.environ.get("SPECTRUMCLAW_PX4_DIR")
    if configured:
        return Path(configured)
    return _project_root() / "simulation" / "third_party" / "PX4-Autopilot"


def _load_runtime_record() -> dict[str, Any] | None:
    try:
        data = json.loads(_pid_file().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError, TypeError):
        return None


def _is_alive(pid: int | None) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:
        # os.kill(pid, 0) reports a zombie as existing. Treat it as stopped so
        # a failed simulator cannot leave the control API permanently running.
        if Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()[2] == "Z":
            return False
    except OSError:
        return False
    return True


def _bridge_listening() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 8765), timeout=0.25):
            return True
    except OSError:
        return False


def camera_frame_path(direction: str = "front") -> Path:
    # JPEGs are disposable real-time transport, not simulator state.  Keep
    # them on tmpfs so atomic frame replacement cannot turn a 24 FPS camera
    # into a network-filesystem I/O benchmark.  The bridge status and all
    # durable logs remain under the regular runtime root.
    cache_root = Path(os.environ.get("SPECTRUMCLAW_UAV_CAMERA_CACHE", "/dev/shm/spectrumclaw-uav-cameras"))
    return cache_root / f"{direction}.jpg"


def _camera_status_path() -> Path:
    return _state_dir() / "gazebo-camera.status.json"


def _px4_control_script() -> Path:
    return _project_root() / "simulation" / "bridges" / "px4_control.py"


def _manual_control_script() -> Path:
    return _project_root() / "simulation" / "bridges" / "px4_manual_control_bridge.py"


def _manual_control_state_path() -> Path:
    return _state_dir() / "px4-manual-control.json"


def _manual_control_status_path() -> Path:
    return _state_dir() / "px4-manual-control.status.json"


def _manual_control_session_path() -> Path:
    """One browser lease per bridge generation; never a flight-control secret."""
    return _state_dir() / "px4-manual-control.session.json"


def _agent_navigation_state_path() -> Path:
    """Private desired-position channel consumed by the single MAVLink bridge."""
    return _state_dir() / "px4-agent-navigation.json"


def _gui_log_path() -> Path:
    return _log_dir() / "gazebo-gui.log"


def _gui_is_listening() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", GAZEBO_GUI_VNC_PORT), timeout=0.25):
            return True
    except OSError:
        return False


def _gui_status(record: dict[str, Any] | None) -> dict[str, Any]:
    gui = record.get("gui", {}) if record else {}
    pid = gui.get("pid") if isinstance(gui, dict) else None
    running = _is_alive(pid)
    listening = running and _gui_is_listening()
    return {
        "state": "online" if listening else "starting" if running else "stopped",
        "process_running": running,
        "vnc_listening": listening,
        "display": GAZEBO_GUI_DISPLAY,
        "embed_url": "/uav-gui/vnc.html?autoconnect=1&resize=scale&show_dot=0&path=api/uav-spectrum-sim/gui/rfb",
        "log_file": str(_gui_log_path()),
    }


def _stages() -> dict[str, bool]:
    state_dir = _state_dir()
    return {name: (state_dir / f"{name}.done").is_file() for name in REQUIRED_STAGES}


def _camera_status(record: dict[str, Any] | None) -> dict[str, Any]:
    camera = record.get("camera", {}) if record else {}
    pid = camera.get("pid") if isinstance(camera, dict) else None
    bridge_running = _is_alive(pid)
    details: dict[str, Any] = {}
    try:
        parsed = json.loads(_camera_status_path().read_text(encoding="utf-8"))
        if isinstance(parsed, dict):
            details = parsed
    except (OSError, ValueError, TypeError):
        pass

    camera_details = details.get("cameras", {}) if isinstance(details.get("cameras"), dict) else {}
    streams = {
        direction: {
            "ready": camera_frame_path(direction).is_file() and bool(camera_details.get(direction, {}).get("online")),
            "frame_url": f"/api/uav-spectrum-sim/camera/{direction}",
            "topic": camera_details.get(direction, {}).get("topic", ""),
            "frames": camera_details.get(direction, {}).get("frames", 0),
            "written_frames": camera_details.get(direction, {}).get("written_frames", 0),
            "updated_at": camera_details.get(direction, {}).get("last_frame_at"),
            "last_write_at": camera_details.get(direction, {}).get("last_write_at"),
        }
        for direction in CAMERA_DIRECTIONS
    }
    frame_present = all(stream["ready"] for stream in streams.values())
    if bridge_running and frame_present:
        state = "online"
    elif bridge_running:
        state = "waiting"
    else:
        state = "stopped"
    return {
        "state": state,
        "bridge_running": bridge_running,
        "frame_present": frame_present,
        "frame_url": streams["front"]["frame_url"],
        "topic": streams["front"]["topic"],
        "frames": streams["front"]["frames"],
        "updated_at": streams["front"]["updated_at"],
        "error": details.get("error", ""),
        "streams": streams,
        "vehicle": details.get("vehicle", {}),
        "lidar": details.get("lidar", {}),
    }


def _manual_control_status(record: dict[str, Any] | None) -> dict[str, Any]:
    manual = record.get("manual", {}) if record else {}
    pid = manual.get("pid") if isinstance(manual, dict) else None
    details: dict[str, Any] = {}
    try:
        parsed = json.loads(_manual_control_status_path().read_text(encoding="utf-8"))
        if isinstance(parsed, dict):
            details = parsed
    except (OSError, ValueError, TypeError):
        pass
    running = _is_alive(pid)
    # The bridge leaves its final status file behind after a normal simulator
    # stop.  Never surface that stale payload as an active browser control.
    if not running:
        details = {}
    # New bridges report lease freshness explicitly.  Keep the fallback for a
    # previously written status file so a rolling deployment never fabricates
    # a control-state change before its bridge is restarted.
    effective_enabled = bool(details.get("lease_fresh", details.get("enabled")))
    armed = details.get("armed")
    offboard_active = details.get("offboard_active")
    if effective_enabled and armed is False:
        state = "grounded"
    elif effective_enabled and offboard_active is True:
        state = "active"
    elif effective_enabled and details.get("offboard_acknowledged"):
        state = "armed"
    elif effective_enabled:
        state = "arming"
    else:
        state = "standby" if running else "stopped"
    return {
        "state": state,
        "bridge_running": running,
        "enabled": effective_enabled,
        "offboard_acknowledged": bool(details.get("offboard_acknowledged")),
        "armed": bool(armed),
        "offboard_active": bool(offboard_active),
        "flight_mode": str(details.get("flight_mode") or "unknown"),
        "last_input_at": details.get("last_input_at"),
        "error": details.get("last_error", ""),
    }


def _agent_navigation_status(record: dict[str, Any] | None) -> dict[str, Any]:
    """Report whether the current bridge was launched with agent-target support."""
    manual = record.get("manual", {}) if record else {}
    pid = manual.get("pid") if isinstance(manual, dict) else None
    running = _is_alive(pid)
    supports_agent_target = False
    if running and isinstance(pid, int):
        try:
            argv = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
            supports_agent_target = b"--agent-state" in argv
        except OSError:
            pass
    return {
        "state": "ready" if supports_agent_target else "restart_required" if running else "stopped",
        "ready": supports_agent_target,
        "bridge_running": running,
        "state_file": str(_agent_navigation_state_path()),
    }
def scene_definition() -> dict[str, Any]:
    """Return the declared mission geometry, not live vehicle telemetry."""
    return {
        "frame": "local-ENU",
        "area_m": [120, 120],
        "vehicle": {"model": "PX4 x500（五路机载相机 + 追随相机 + 2D LiDAR）", "mode": "headless SITL", "world": GAZEBO_WORLD},
        # These are declared directly from simulation/worlds/urban_block.sdf.
        # They are scene semantics for the operations UI, not inferred objects.
        "objects": [
            {"id": "office_east", "label": "东侧办公楼", "kind": "building", "position_m": [13, 12], "size_m": [10, 10, 18]},
            {"id": "tower_northwest", "label": "西北塔楼", "kind": "building", "position_m": [-13, 14], "size_m": [9, 8, 22]},
            {"id": "residential_west", "label": "西侧住宅", "kind": "building", "position_m": [-16, -11], "size_m": [12, 10, 15]},
            {"id": "warehouse_southeast", "label": "东南仓库", "kind": "building", "position_m": [14, -14], "size_m": [16, 8, 10]},
            {"id": "library_north", "label": "北侧图书馆", "kind": "building", "position_m": [0, 25], "size_m": [18, 7, 11]},
            {"id": "clinic_west", "label": "西侧诊所", "kind": "building", "position_m": [-27, 7], "size_m": [10, 10, 12]},
        ],
        # The RF layer is intentionally not active in this phase.  Keeping a
        # typed, disabled interface lets the same situational panel show real
        # signal sources later without pretending they are currently measured.
        "signal_sources": [
            {"id": "tx-01", "label": "信号源接口 01", "position_m": [42, 36], "frequency_mhz": 2400, "enabled": False},
            {"id": "tx-02", "label": "信号源接口 02", "position_m": [-38, -32], "frequency_mhz": 2450, "enabled": False},
        ],
        "transmitters": [
            {"id": "tx-01", "position_m": [42, 36], "frequency_mhz": 2400},
            {"id": "tx-02", "position_m": [-38, -32], "frequency_mhz": 2450},
        ],
        "waypoints_m": [[0, 0], [0, -30], [-30, -30], [30, -30], [30, 30], [-30, 30], [0, 30], [0, 0]],
        "note": "机载五路相机正在渲染 Gazebo 三维场景；建筑物来自 urban_block 场景声明，实时位置与 LiDAR 来自当前桥接遥测。频谱信号源接口尚未激活。",
    }


def get_runtime_status() -> dict[str, Any]:
    stages = _stages()
    record = _load_runtime_record()
    pid = record.get("pid") if record else None
    running = _is_alive(pid)
    if record and not running:
        _pid_file().unlink(missing_ok=True)
        record = None

    camera = _camera_status(record)
    gui = _gui_status(record)
    manual = _manual_control_status(record)
    agent_navigation = _agent_navigation_status(record)

    return {
        "status": "ok",
        "environment_ready": all(stages.values()),
        "stages": stages,
        "runtime": {
            "state": "running" if running else "stopped",
            "pid": pid if running else None,
            "started_at": record.get("started_at") if running and record else None,
            "log_file": str(_log_dir() / "px4_gazebo.live.log"),
            "camera": camera,
            "gui": gui,
            "manual": manual,
            "agent_navigation": agent_navigation,
        },
        "components": {
            "ros2": {"ready": stages["01_system"], "label": "ROS 2 Humble"},
            "gazebo": {"ready": stages["04_ros_gazebo_px4_smoke"], "label": "Gazebo Harmonic"},
            "px4": {"ready": stages["02_px4"], "label": "PX4 v1.17"},
            "sionna_rt": {"ready": stages["05_sionna_rt_smoke"], "label": "Sionna RT 2.0.1"},
            "foxglove": {"ready": stages["07_debug_bridge"], "listening": _bridge_listening(), "label": "Foxglove Bridge"},
            "gazebo_camera": {"ready": camera["state"] == "online", "label": "Gazebo 3D Camera Stream"},
            "gazebo_gui": {"ready": gui["state"] == "online", "label": "Embedded Gazebo GUI"},
            "manual_control": {"ready": manual["bridge_running"], "label": "PX4 Manual Control Bridge"},
            "agent_navigation": {"ready": agent_navigation["ready"], "label": "PX4 Agent Navigation Bridge"},
        },
        "scene": scene_definition(),
    }


def get_live_snapshot() -> dict[str, Any]:
    """Compact real-time state used by the local WebGL UAV view.

    Camera pixels stay at their cache URLs; this stream carries only current
    frame counters and vehicle pose so the browser avoids high-latency desktop
    remoting while still rendering the real simulator state.
    """
    status = get_runtime_status()
    runtime = status["runtime"]
    camera = runtime["camera"]
    return {
        "type": "uav_live_v1",
        "timestamp": time.time(),
        "runtime": {
            "state": runtime["state"],
            "started_at": runtime["started_at"],
            "manual": runtime["manual"],
            "camera": {
                "state": camera["state"],
                "streams": camera["streams"],
                "lidar": camera.get("lidar", {}),
            },
        },
        "vehicle": camera.get("vehicle", {}),
        "scene": {
            "frame": status["scene"]["frame"],
            "vehicle_model": status["scene"]["vehicle"]["model"],
            "world": status["scene"]["vehicle"]["world"],
        },
    }


def execute_vehicle_command(action: str, altitude_m: float | None = None) -> dict[str, Any]:
    """Run an allow-listed PX4 action through the host MAVLink adapter.

    This deliberately exposes no arbitrary PX4 shell or Gazebo pose mutation.
    It is restricted to the simulation process currently owned by this module.
    """
    if get_runtime_status()["runtime"]["state"] != "running":
        raise RuntimeError("请先启动 PX4/Gazebo 仿真，再执行无人机控制指令")
    script = _px4_control_script()
    python = Path(os.environ.get("SPECTRUMCLAW_GZ_PYTHON", "/usr/bin/python3"))
    if not script.is_file() or not python.is_file():
        raise RuntimeError("未找到 PX4 MAVLink 控制适配器")
    command = [str(python), str(script), action]
    if altitude_m is not None:
        command.extend(["--altitude-m", str(float(altitude_m))])
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=18, check=False)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("PX4 控制命令超时") from exc
    output = completed.stdout.strip().splitlines()
    payload: dict[str, Any] = {}
    if output:
        try:
            parsed = json.loads(output[-1])
            if isinstance(parsed, dict):
                payload = parsed
        except ValueError:
            pass
    if completed.returncode or not payload.get("ok"):
        detail = payload.get("error") or completed.stderr.strip() or "PX4 未接受控制命令"
        raise RuntimeError(str(detail))
    return payload


def _write_manual_control_state(payload: dict[str, Any]) -> None:
    path = _manual_control_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload), encoding="utf-8")
    temporary.replace(path)


def _write_agent_navigation_state(payload: dict[str, Any]) -> None:
    path = _agent_navigation_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload), encoding="utf-8")
    temporary.replace(path)


def _manual_axes(forward: float = 0.0, right: float = 0.0, up: float = 0.0, yaw: float = 0.0) -> dict[str, float]:
    values = {"forward": forward, "right": right, "up": up, "yaw": yaw}
    sanitized: dict[str, float] = {}
    for name, value in values.items():
        try:
            sanitized[name] = max(-1.0, min(1.0, float(value)))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} 必须在 -1 到 1 之间") from exc
    return sanitized


def write_manual_control_intent(enabled: bool, forward: float = 0.0, right: float = 0.0, up: float = 0.0, yaw: float = 0.0) -> dict[str, float]:
    """Write a bounded intent without re-reading process state on every WS packet."""
    sanitized = _manual_axes(forward, right, up, yaw)
    _write_manual_control_state({"enabled": bool(enabled), **sanitized, "updated_at": time.time()})
    return sanitized


def issue_manual_control_session() -> str:
    """Issue a short-lived browser lease for the current manual-control bridge.

    This prevents a page opened before a simulator restart from reconnecting
    into the new bridge and replaying stale zero-valued input.
    """
    token = secrets.token_urlsafe(24)
    _write_manual_control_state({"enabled": False, "forward": 0.0, "right": 0.0, "up": 0.0, "yaw": 0.0, "updated_at": time.time()})
    _write_manual_control_session({"token": token, "expires_at": time.time() + 30 * 60})
    return token


def _write_manual_control_session(payload: dict[str, Any]) -> None:
    path = _manual_control_session_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload), encoding="utf-8")
    temporary.replace(path)


def manual_control_session_valid(token: str | None) -> bool:
    if not token:
        return False
    try:
        session = json.loads(_manual_control_session_path().read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    return (
        isinstance(session, dict)
        and isinstance(session.get("token"), str)
        and secrets.compare_digest(session["token"], token)
        and float(session.get("expires_at", 0)) > time.time()
    )


def invalidate_manual_control_session() -> None:
    _manual_control_session_path().unlink(missing_ok=True)


def set_manual_control(enabled: bool, forward: float = 0.0, right: float = 0.0, up: float = 0.0, yaw: float = 0.0) -> dict[str, Any]:
    """Validate browser manual-control access; MAVLink remains server-side only."""
    status = get_runtime_status()
    if status["runtime"]["state"] != "running":
        raise RuntimeError("请先启动 PX4/Gazebo 仿真，再启用遥控")
    manual = status["runtime"]["manual"]
    if not manual["bridge_running"]:
        raise RuntimeError("PX4 遥控桥尚未就绪")
    sanitized = write_manual_control_intent(enabled, forward, right, up, yaw)
    return {"ok": True, "manual": {**manual, "enabled": bool(enabled), **sanitized}}


def disable_manual_control() -> dict[str, Any]:
    """Return control to PX4 hold mode after clearing every velocity axis."""
    # Releasing a browser lease must succeed even while the simulator is
    # stopping.  Clear the state before the best-effort hover command so the
    # agent cannot remain blocked by a stale UI session after a command error.
    write_manual_control_intent(False)
    invalidate_manual_control_session()
    try:
        hover = execute_vehicle_command("hover")
    except (RuntimeError, ValueError) as exc:
        return {
            "ok": True,
            "manual": {"enabled": False},
            "hover": {"ok": False, "message": str(exc)},
        }
    return {"ok": True, "manual": {"enabled": False}, "hover": hover}


def write_agent_navigation_target(target_enu_m: list[float], expires_in_s: float = 45.0) -> dict[str, Any]:
    """Set a bounded agent position target for the existing MAVLink owner.

    This function is intentionally private to the mission service.  It does
    not accept raw MAVLink fields or arbitrary velocity commands.
    """
    if not isinstance(target_enu_m, list) or len(target_enu_m) != 3:
        raise ValueError("agent target 必须是 [east_m, north_m, altitude_m]")
    try:
        east, north, altitude = (float(value) for value in target_enu_m)
    except (TypeError, ValueError) as exc:
        raise ValueError("agent target 必须是数值坐标") from exc
    if not (-35.0 <= east <= 35.0 and -35.0 <= north <= 35.0 and 18.0 <= altitude <= 20.0):
        raise ValueError("agent target 超出 urban_block 安全航线范围")
    ttl = min(60.0, max(5.0, float(expires_in_s)))
    _write_agent_navigation_state({
        "enabled": True,
        "target_enu_m": [east, north, altitude],
        "updated_at": time.time(),
        "expires_at": time.time() + ttl,
    })
    return {"ok": True, "target_enu_m": [east, north, altitude], "expires_in_s": ttl}


def clear_agent_navigation_target() -> dict[str, Any]:
    """Make the MAVLink bridge stop consuming an agent position target."""
    _write_agent_navigation_state({"enabled": False, "updated_at": time.time()})
    return {"ok": True}


def _spawn_sidecar_process(command: list[str], log_file: Any, env: dict[str, str] | None = None) -> subprocess.Popen[Any]:
    return subprocess.Popen(
        command,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        env=env,
        start_new_session=True,
    )


def _start_camera_bridge() -> dict[str, Any]:
    """Start the Gazebo-Transport-to-JPEG sidecar used by the web UI.

    This mirrors AerialClaw's sensor bridge topology.  The sidecar deliberately
    uses Ubuntu's Python 3.10 Gazebo bindings while the SpectrumClaw service
    remains in its established Python 3.11 conda environment.
    """
    script = _project_root() / "simulation" / "bridges" / "gazebo_camera_bridge.py"
    python = Path(os.environ.get("SPECTRUMCLAW_GZ_PYTHON", "/usr/bin/python3"))
    if not script.is_file() or not python.is_file():
        raise RuntimeError("未找到 Gazebo 相机桥接程序或系统 Python 运行时")
    log_path = _log_dir() / "gazebo_camera_bridge.log"
    command = [
        str(python), str(script),
        "--output-dir", str(camera_frame_path().parent),
        "--status", str(_camera_status_path()),
        "--max-fps", "2",
        # Gazebo's 30 Hz source reaches about 24 FPS under the current urban
        # world load.  Do not add a near-equal software cap: phase rounding
        # can halve the visible stream instead of holding it near 24 FPS.
        "--chase-max-fps", "60",
    ]
    environment = dict(os.environ)
    environment.setdefault("GZ_IP", "127.0.0.1")
    with log_path.open("ab", buffering=0) as log_file:
        process = _spawn_sidecar_process(command, log_file, env=environment)
    return {"pid": process.pid, "log_file": str(log_path)}


def _start_manual_control_bridge() -> dict[str, Any]:
    script = _manual_control_script()
    python = Path(os.environ.get("SPECTRUMCLAW_GZ_PYTHON", "/usr/bin/python3"))
    if not script.is_file() or not python.is_file():
        raise RuntimeError("未找到 PX4 手动控制桥或系统 Python 运行时")
    _write_manual_control_state({"enabled": False, "forward": 0.0, "right": 0.0, "up": 0.0, "yaw": 0.0, "updated_at": time.time()})
    invalidate_manual_control_session()
    clear_agent_navigation_target()
    log_path = _log_dir() / "px4_manual_control_bridge.log"
    command = [
        str(python), str(script),
        "--state", str(_manual_control_state_path()),
        "--agent-state", str(_agent_navigation_state_path()),
        "--status", str(_manual_control_status_path()),
    ]
    with log_path.open("ab", buffering=0) as log_file:
        process = _spawn_sidecar_process(command, log_file, env=dict(os.environ))
    return {"pid": process.pid, "log_file": str(log_path)}


def _terminate_process_group(pid: int | None) -> None:
    if not _is_alive(pid):
        return
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + 8
    while _is_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.2)
    if _is_alive(pid):
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def start_gui_session() -> dict[str, Any]:
    """Start a server-side native Gazebo GUI for the embedded noVNC canvas."""
    status = get_runtime_status()
    if status["runtime"]["state"] != "running":
        raise RuntimeError("请先启动 PX4/Gazebo 仿真，再打开交互式 Gazebo 视图")
    if status["runtime"]["gui"]["state"] in {"starting", "online"}:
        return status

    record = _load_runtime_record()
    if not record:
        raise RuntimeError("未找到当前仿真运行记录")
    script = _project_root() / "simulation" / "gui" / "start_gazebo_gui_session.sh"
    if not script.is_file():
        raise RuntimeError("未找到 Gazebo GUI 会话启动脚本")
    px4_dir = _px4_dir()
    environment = dict(os.environ)
    environment.update(
        {
            "SPECTRUMCLAW_UAV_RUNTIME_ROOT": str(_runtime_root()),
            "SPECTRUMCLAW_PX4_DIR": str(px4_dir),
            "SPECTRUMCLAW_GAZEBO_GUI_DISPLAY": GAZEBO_GUI_DISPLAY,
            "SPECTRUMCLAW_GAZEBO_GUI_VNC_PORT": str(GAZEBO_GUI_VNC_PORT),
        }
    )
    _log_dir().mkdir(parents=True, exist_ok=True)
    with _gui_log_path().open("ab", buffering=0) as log_file:
        process = subprocess.Popen(
            ["bash", str(script)],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            env=environment,
        )
    record["gui"] = {"pid": process.pid, "started_at": time.time(), "log_file": str(_gui_log_path())}
    _pid_file().write_text(json.dumps(record), encoding="utf-8")
    return get_runtime_status()


def stop_gui_session() -> dict[str, Any]:
    record = _load_runtime_record()
    if not record:
        return get_runtime_status()
    gui = record.get("gui", {})
    _terminate_process_group(gui.get("pid") if isinstance(gui, dict) else None)
    record.pop("gui", None)
    _pid_file().write_text(json.dumps(record), encoding="utf-8")
    return get_runtime_status()


def start_simulation() -> dict[str, Any]:
    status = get_runtime_status()
    if not status["environment_ready"]:
        missing = [name for name, complete in status["stages"].items() if not complete]
        raise RuntimeError(f"仿真环境未完成：{', '.join(missing)}")
    if status["runtime"]["state"] == "running":
        return status

    px4_dir = _px4_dir()
    if not (px4_dir / "Makefile").is_file():
        raise RuntimeError(f"未找到 PX4 源码：{px4_dir}")

    _state_dir().mkdir(parents=True, exist_ok=True)
    _log_dir().mkdir(parents=True, exist_ok=True)
    for direction in CAMERA_DIRECTIONS:
        camera_frame_path(direction).unlink(missing_ok=True)
    _camera_status_path().unlink(missing_ok=True)
    log_path = _log_dir() / "px4_gazebo.live.log"
    bundled_model_dir = _project_root() / "simulation" / "models" / CAMERA_MODEL
    bundled_world = _project_root() / "simulation" / "worlds" / f"{GAZEBO_WORLD}.sdf"
    model_dir = px4_dir / "Tools" / "simulation" / "gz" / "models" / CAMERA_MODEL
    worlds_dir = px4_dir / "Tools" / "simulation" / "gz" / "worlds"
    if bundled_model_dir.is_dir():
        shutil.copytree(bundled_model_dir, model_dir, dirs_exist_ok=True)
    if bundled_world.is_file():
        worlds_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(bundled_world, worlds_dir / bundled_world.name)
    if not model_dir.is_dir():
        raise RuntimeError(f"PX4/Gazebo 中缺少相机模型：{CAMERA_MODEL}")
    build_dir = px4_dir / "build" / "px4_sitl_default"
    px4_bin = build_dir / "bin" / "px4"
    world = px4_dir / "Tools" / "simulation" / "gz" / "worlds" / f"{GAZEBO_WORLD}.sdf"
    models_root = px4_dir / "Tools" / "simulation" / "gz" / "models"
    if not px4_bin.is_file() or not world.is_file():
        raise RuntimeError("PX4/Gazebo 已安装但缺少 SITL 构建产物或城市街区场景")
    gz_env = build_dir / "rootfs" / "gz_env.sh"
    if not gz_env.is_file():
        raise RuntimeError("PX4/Gazebo 已安装但缺少 Gazebo 运行环境脚本")
    command = (
        "set -e; set +u; source /opt/ros/humble/setup.bash; "
        f"source {shlex.quote(str(gz_env))}; set -u; "
        f"export PX4_GZ_MODELS={shlex.quote(str(models_root))}; "
        f"export PX4_GZ_WORLDS={shlex.quote(str(world.parent))}; "
        f"export GZ_IP=127.0.0.1 PX4_SYS_AUTOSTART=4001 PX4_SIMULATOR=gz PX4_GZ_WORLD={GAZEBO_WORLD} PX4_SIM_MODEL={PX4_SIM_MODEL} PX4_GZ_STANDALONE=1; "
        f"gz sim --verbose=1 -r -s {shlex.quote(str(world))} >/dev/null 2>&1 & sleep 6; "
        f"cd {shlex.quote(str(build_dir))}; exec ./bin/px4 -s ./etc/init.d-posix/rcS </dev/null >/dev/null 2>&1"
    )
    with log_path.open("ab", buffering=0) as log_file:
        process = subprocess.Popen(
            ["bash", "-lc", command],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            stdin=subprocess.DEVNULL,
        )
    camera: dict[str, Any] | None = None
    try:
        camera = _start_camera_bridge()
        manual = _start_manual_control_bridge()
    except Exception:
        _terminate_process_group(process.pid)
        if camera:
            _terminate_process_group(camera.get("pid"))
        raise
    _pid_file().write_text(
        json.dumps({"pid": process.pid, "started_at": time.time(), "command": f"PX4 standalone {PX4_SIM_MODEL}", "camera": camera, "manual": manual}),
        encoding="utf-8",
    )
    return get_runtime_status()


def stop_simulation() -> dict[str, Any]:
    record = _load_runtime_record()
    pid = record.get("pid") if record else None
    gui = record.get("gui", {}) if record else {}
    _terminate_process_group(gui.get("pid") if isinstance(gui, dict) else None)
    _terminate_process_group(pid)
    camera = record.get("camera", {}) if record else {}
    _terminate_process_group(camera.get("pid") if isinstance(camera, dict) else None)
    manual = record.get("manual", {}) if record else {}
    _terminate_process_group(manual.get("pid") if isinstance(manual, dict) else None)
    invalidate_manual_control_session()
    _pid_file().unlink(missing_ok=True)
    return get_runtime_status()
