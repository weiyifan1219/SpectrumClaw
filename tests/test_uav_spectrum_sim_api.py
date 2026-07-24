"""Contract tests for the headless UAV spectrum simulation API."""

from __future__ import annotations

import os
from pathlib import Path


def _ready_runtime(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    from backend.skills.uav_spectrum_sim import runtime

    runtime_root = tmp_path / "runtime"
    project_root = tmp_path / "project"
    state_dir = runtime_root / "install-state" / runtime.PHASE_NAME
    state_dir.mkdir(parents=True)
    (project_root / "simulation" / "third_party" / "PX4-Autopilot").mkdir(parents=True)
    for stage in runtime.REQUIRED_STAGES:
        (state_dir / f"{stage}.done").touch()
    monkeypatch.setenv("SPECTRUMCLAW_UAV_RUNTIME_ROOT", str(runtime_root))
    monkeypatch.setenv("SPECTRUMCLAW_UAV_PROJECT_ROOT", str(project_root))
    return runtime_root, project_root


def test_status_reports_real_stage_markers(tmp_path, monkeypatch):
    _ready_runtime(tmp_path, monkeypatch)
    from backend.skills.uav_spectrum_sim.runtime import get_runtime_status

    data = get_runtime_status()

    assert data["status"] == "ok"
    assert data["environment_ready"] is True
    assert all(data["stages"].values())
    assert data["runtime"]["state"] == "stopped"
    assert data["scene"]["vehicle"]["model"] == "PX4 x500（五路机载相机 + 追随相机 + 2D LiDAR）"
    assert data["scene"]["vehicle"]["world"] == "urban_block"
    assert data["scene"]["note"].startswith("机载五路相机正在渲染")


def test_start_rejects_incomplete_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("SPECTRUMCLAW_UAV_RUNTIME_ROOT", str(tmp_path / "runtime"))
    from backend.skills.uav_spectrum_sim.runtime import start_simulation

    try:
        start_simulation()
    except RuntimeError as exc:
        assert "仿真环境未完成" in str(exc)
    else:
        raise AssertionError("incomplete environment must not start PX4")


def test_start_records_a_new_process_session(tmp_path, monkeypatch):
    _ready_runtime(tmp_path, monkeypatch)
    from backend.skills.uav_spectrum_sim import runtime

    px4_dir = Path(os.environ["SPECTRUMCLAW_UAV_PROJECT_ROOT"]) / "simulation" / "third_party" / "PX4-Autopilot"
    (px4_dir / "Makefile").touch()
    build_dir = px4_dir / "build" / "px4_sitl_default"
    (build_dir / "bin").mkdir(parents=True)
    (build_dir / "bin" / "px4").touch()
    (build_dir / "rootfs").mkdir(parents=True)
    (build_dir / "rootfs" / "gz_env.sh").touch()
    (build_dir / "etc" / "init.d-posix").mkdir(parents=True)
    (build_dir / "etc" / "init.d-posix" / "rcS").touch()
    world_dir = px4_dir / "Tools" / "simulation" / "gz" / "worlds"
    model_dir = px4_dir / "Tools" / "simulation" / "gz" / "models" / runtime.CAMERA_MODEL
    world_dir.mkdir(parents=True)
    model_dir.mkdir(parents=True)
    bundled_world_dir = Path(os.environ["SPECTRUMCLAW_UAV_PROJECT_ROOT"]) / "simulation" / "worlds"
    bundled_world_dir.mkdir(parents=True)
    (bundled_world_dir / f"{runtime.GAZEBO_WORLD}.sdf").write_text('<sdf version="1.9"/>', encoding="utf-8")
    seen = {}

    class Process:
        pid = os.getpid()

    def fake_popen(args, **kwargs):
        seen["args"] = args
        seen["kwargs"] = kwargs
        return Process()

    monkeypatch.setattr(runtime.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(runtime, "_start_camera_bridge", lambda: {"pid": os.getpid()})
    monkeypatch.setattr(runtime, "_start_manual_control_bridge", lambda: {"pid": os.getpid()})
    data = runtime.start_simulation()

    assert seen["kwargs"]["start_new_session"] is True
    assert data["runtime"]["state"] == "running"
    assert "PX4_SIM_MODEL=gz_x500_lidar_2d_cam" in seen["args"][-1]
    assert f"PX4_GZ_WORLD={runtime.GAZEBO_WORLD}" in seen["args"][-1]
    assert (world_dir / f"{runtime.GAZEBO_WORLD}.sdf").is_file()


def test_stale_manual_status_is_not_reported_after_stop(tmp_path, monkeypatch):
    _ready_runtime(tmp_path, monkeypatch)
    from backend.skills.uav_spectrum_sim import runtime

    runtime._manual_control_status_path().write_text(
        '{"enabled": true, "offboard_acknowledged": true}', encoding="utf-8"
    )

    status = runtime._manual_control_status(None)

    assert status["state"] == "stopped"
    assert status["bridge_running"] is False
    assert status["enabled"] is False


def test_disarmed_manual_bridge_is_not_reported_as_active_offboard(tmp_path, monkeypatch):
    _ready_runtime(tmp_path, monkeypatch)
    from backend.skills.uav_spectrum_sim import runtime

    runtime._manual_control_status_path().write_text(
        '{"enabled": true, "offboard_acknowledged": true, "armed": false, "offboard_active": false, "flight_mode": "Hold"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime, "_is_alive", lambda pid: True)

    status = runtime._manual_control_status({"manual": {"pid": 123}})

    assert status["state"] == "grounded"
    assert status["offboard_active"] is False
    assert status["armed"] is False


def test_expired_manual_lease_is_not_reported_as_browser_takeover(tmp_path, monkeypatch):
    _ready_runtime(tmp_path, monkeypatch)
    from backend.skills.uav_spectrum_sim import runtime

    runtime._manual_control_status_path().write_text(
        '{"enabled": true, "lease_fresh": false, "armed": true, "offboard_active": true}',
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime, "_is_alive", lambda pid: True)

    status = runtime._manual_control_status({"manual": {"pid": 123}})

    assert status["enabled"] is False
    assert status["state"] == "standby"


def test_manual_control_writes_a_bounded_server_side_intent(tmp_path, monkeypatch):
    _ready_runtime(tmp_path, monkeypatch)
    from backend.skills.uav_spectrum_sim import runtime

    monkeypatch.setattr(runtime, "get_runtime_status", lambda: {
        "runtime": {"state": "running", "manual": {"bridge_running": True}},
    })
    result = runtime.set_manual_control(True, forward=3.0, right=-2.0, up=0.25, yaw=-5.0)

    assert result["ok"] is True
    state = __import__("json").loads(runtime._manual_control_state_path().read_text(encoding="utf-8"))
    assert state["enabled"] is True
    assert state["forward"] == 1.0
    assert state["right"] == -1.0
    assert state["up"] == 0.25
    assert state["yaw"] == -1.0


def test_live_manual_intent_reuses_bounded_writer_without_status_poll(tmp_path, monkeypatch):
    _ready_runtime(tmp_path, monkeypatch)
    from backend.skills.uav_spectrum_sim import runtime

    monkeypatch.setattr(runtime, "get_runtime_status", lambda: (_ for _ in ()).throw(AssertionError("live path must not poll status")))
    axes = runtime.write_manual_control_intent(True, forward=-5, right=0.1, up=9, yaw=-2)

    assert axes == {"forward": -1.0, "right": 0.1, "up": 1.0, "yaw": -1.0}
    state = __import__("json").loads(runtime._manual_control_state_path().read_text(encoding="utf-8"))
    assert state["enabled"] is True
    assert state["forward"] == -1.0


def test_manual_browser_session_is_invalidated_across_a_bridge_restart(tmp_path, monkeypatch):
    _ready_runtime(tmp_path, monkeypatch)
    from backend.skills.uav_spectrum_sim import runtime

    first = runtime.issue_manual_control_session()

    assert runtime.manual_control_session_valid(first) is True
    assert runtime.manual_control_session_valid("stale-browser-token") is False

    runtime.invalidate_manual_control_session()

    assert runtime.manual_control_session_valid(first) is False
