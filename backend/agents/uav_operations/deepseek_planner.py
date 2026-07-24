"""DeepSeek-assisted proposal author behind the UAV task compiler boundary."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable
from typing import Any

from .mission_author import MissionAuthor
from .sandbox import MissionSandbox


class DeepSeekMissionPlanner:
    """Generate an auditable model proposal; never permit it to fly directly."""

    def __init__(self, author: MissionAuthor, sandbox: MissionSandbox, *, ask: Callable[[str], str] | None = None) -> None:
        self._author = author
        self._sandbox = sandbox
        self._ask = ask or self._ask_deepseek

    @staticmethod
    def _prompt(intent: str) -> str:
        return (
            "你是无人机仿真任务规划子智能体。仅返回 JSON，不要 Markdown。"
            "template 仅可为 inspect_safe_perimeter、collect_camera_evidence、search_safe_route、"
            "takeoff_and_hover、hover、land、return_to_launch。"
            "landmark 仅能为 north_gate、south_gate、east_gate、west_gate 或 null。"
            "禁止坐标、速度、MAVLink、Shell、Python、网络请求或可执行代码。"
            "格式：{\"template\":string,\"landmark\":string|null,\"summary\":string}。"
            f"用户意图：{intent}"
        )

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any]:
        match = re.search(r"\{[\s\S]*\}", text.strip())
        if not match:
            raise ValueError("模型未返回 JSON 对象")
        parsed = json.loads(match.group(0))
        if not isinstance(parsed, dict):
            raise ValueError("模型未返回 JSON 对象")
        return parsed

    @staticmethod
    def _ask_deepseek(prompt: str) -> str:
        from ...config import get_settings
        from ...llm.client import chat

        if not get_settings().provider_profile("deepseek").configured:
            raise RuntimeError("DeepSeek 尚未配置")
        reply, _metadata = asyncio.run(chat(
            [{"role": "system", "content": "严格遵守 UAV 任务 JSON 合约。"}, {"role": "user", "content": prompt}],
            provider_override="deepseek",
            thinking_enabled=False,
            tool_names=None,
        ))
        return reply

    def author(self, run_id: str, intent: str) -> tuple[Any, dict[str, Any]]:
        # The deterministic parser establishes the non-negotiable safety
        # contract. The model can describe it, but can never widen it.
        baseline = self._author.author(run_id, intent)
        record: dict[str, Any] = {
            "provider": "deterministic_safe_compiler",
            "accepted": True,
            "template": baseline.template,
            "landmark": baseline.landmark,
        }
        try:
            suggestion = self._extract_json(self._ask(self._prompt(intent)))
            if suggestion.get("template") != baseline.template or suggestion.get("landmark") != baseline.landmark:
                raise ValueError("DeepSeek 提案与受限意图编译结果不一致")
            record.update({"provider": "deepseek_validated", "summary": str(suggestion.get("summary", ""))[:320]})
        except Exception as exc:
            # A bad or unavailable model degrades to the same deterministic
            # plan, never to an unvalidated action.
            record.update({"accepted": False, "fallback_reason": str(exc)[:240]})
        self._sandbox.write_json(run_id, "planner_record.json", record)
        return baseline, record
