"""Isolation tests for the UAV mission-author sandbox."""

from __future__ import annotations

from pathlib import Path

import pytest


def test_sandbox_refuses_path_escape_and_writes_only_declared_artifacts(tmp_path: Path):
    from backend.agents.uav_operations.sandbox import MissionSandbox

    sandbox = MissionSandbox(tmp_path)
    run_dir = sandbox.create_run("run_safe_001")

    written = sandbox.write_json("run_safe_001", "mission_plan.json", {"template": "inspect_safe_perimeter"})
    program = sandbox.write_json("run_safe_001", "mission_program.json", {"language": "spectrumclaw-uav-dsl/v1"})

    assert written == run_dir / "mission_plan.json"
    assert written.is_file()
    assert program == run_dir / "mission_program.json"
    with pytest.raises(ValueError, match="不允许"):
        sandbox.write_json("run_safe_001", "../outside.json", {})
    with pytest.raises(ValueError, match="不允许"):
        sandbox.write_text("run_safe_001", "script.py", "print('unsafe')")


def test_mission_author_maps_only_fixed_templates_and_safe_landmarks(tmp_path: Path):
    from backend.agents.uav_operations.mission_author import MissionAuthor
    from backend.agents.uav_operations.sandbox import MissionSandbox

    author = MissionAuthor(MissionSandbox(tmp_path))
    plan = author.author("run_safe_002", "请巡检安全周界并返回")

    assert plan.template == "inspect_safe_perimeter"
    assert plan.return_home is True
    with pytest.raises(ValueError, match="无法映射"):
        author.author("run_safe_003", "飞到坐标 123, 456 后以 12m/s 搜寻")
