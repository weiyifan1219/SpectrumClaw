"""SpectrumClaw tool registry. Tools are provider-agnostic — registered once, usable across all LLM backends."""

from datetime import datetime, timezone


def _get_current_time() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _get_system_status() -> dict:
    return {
        "frontend": "running (Vite dev server)",
        "backend": "running (FastAPI + uvicorn)",
        "llm": "connected",
        "skills": {
            "frequency_planning": "planned",
            "situation_building": "planned (waiting for REM scripts)",
            "resource_allocation": "planned",
            "interference_analysis": "interface ready",
            "modulation_recognition": "interface ready",
        },
    }


TOOLS = [
    {
        "name": "get_time",
        "description": "获取当前 UTC 时间",
        "parameters": {"type": "object", "properties": {}},
        "handler": _get_current_time,
    },
    {
        "name": "get_system_status",
        "description": "获取 SpectrumClaw 系统各组件的运行状态",
        "parameters": {"type": "object", "properties": {}},
        "handler": _get_system_status,
    },
]


def register_default_tools():
    """Register the default tool set into the global tool registry."""
    from .client import register_tool

    for t in TOOLS:
        register_tool(t["name"], t["handler"], {
            "name": t["name"],
            "description": t["description"],
            "parameters": t["parameters"],
        })
