"""Filesystem boundary for the mission-author subagent."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any


RUN_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{3,96}$")
ALLOWED_ARTIFACTS = {
    "mission_plan.json",
    "mission_program.json",
    "planner_record.json",
    "run_state.json",
    "report.md",
}


class MissionSandbox:
    """Allow a mission author to write only reviewed, non-executable artifacts."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def create_run(self, run_id: str) -> Path:
        if not RUN_ID_PATTERN.fullmatch(run_id):
            raise ValueError("不允许的任务运行标识")
        target = (self.root / run_id).resolve()
        self._ensure_inside(target)
        target.mkdir(parents=True, exist_ok=True)
        return target

    def _artifact_path(self, run_id: str, name: str) -> Path:
        if name not in ALLOWED_ARTIFACTS:
            raise ValueError("不允许写入该沙箱文件")
        run_dir = self.create_run(run_id)
        target = (run_dir / name).resolve()
        self._ensure_inside(target)
        return target

    def _ensure_inside(self, path: Path) -> None:
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("不允许越出任务沙箱") from exc

    @staticmethod
    def _atomic_write(path: Path, content: str) -> Path:
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)
        return path

    def write_json(self, run_id: str, name: str, payload: dict[str, Any]) -> Path:
        if name not in {"mission_plan.json", "mission_program.json", "planner_record.json", "run_state.json"}:
            raise ValueError("不允许写入该沙箱文件")
        return self._atomic_write(
            self._artifact_path(run_id, name),
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        )

    def write_text(self, run_id: str, name: str, content: str) -> Path:
        if name != "report.md":
            raise ValueError("不允许写入该沙箱文件")
        return self._atomic_write(self._artifact_path(run_id, name), content)

    def read_json(self, run_id: str, name: str) -> dict[str, Any] | None:
        path = self._artifact_path(run_id, name)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return None
        return data if isinstance(data, dict) else None
