"""Unified tool registry. Single source of truth for all SpectrumClaw tools.

Each tool entry has:
- name, description, parameters (OpenAI JSON Schema format)
- handler: sync or async callable
- category: "time" | "env" | "weather" | "web" | "knowledge"
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx


# ── handler implementations ──


def _get_current_time() -> str:
    utc = datetime.now(timezone.utc)
    bj = (utc + timedelta(hours=8)).strftime("%Y-%m-%dT%H:%M:%S+08:00")
    return f"UTC: {utc.strftime('%Y-%m-%dT%H:%M:%SZ')} | Beijing: {bj}"


def _get_system_status() -> dict:
    return {
        "frontend": "running",
        "backend": "running",
        "llm": "connected",
        "skills": {
            "frequency_planning": "available",
            "spectrum_construction": "available",
            "resource_allocation": "available",
            "interference_analysis": "reserved",
            "modulation_recognition": "reserved",
        },
    }


def _get_uav_simulation_status() -> dict:
    from ..skills.uav_spectrum_sim.runtime import get_runtime_status
    status = get_runtime_status()
    return {
        "runtime": status["runtime"]["state"],
        "camera": status["runtime"]["camera"]["state"],
        "vehicle": status["runtime"]["camera"].get("vehicle", {}),
        "world": status["scene"]["vehicle"]["world"],
    }


def _control_uav_simulation(action: str, altitude_m: float | None = None) -> dict:
    from ..skills.uav_spectrum_sim.runtime import execute_vehicle_command
    return execute_vehicle_command(action, altitude_m)


def _get_uav_mission_status() -> dict:
    """Read the task-level adapter state shared with the MCP server."""
    from ..skills.uav_spectrum_sim.mission import get_uav_mission_service
    return get_uav_mission_service().inspect()


def _execute_uav_mission(mission: str, altitude_m: float | None = None, landmark: str | None = None) -> dict:
    """Run a bounded, simulator-only mission through the shared adapter."""
    from ..skills.uav_spectrum_sim.mission import get_uav_mission_service
    return get_uav_mission_service().execute(mission, altitude_m, landmark)


def _cancel_uav_mission() -> dict:
    from ..skills.uav_spectrum_sim.mission import get_uav_mission_service
    return get_uav_mission_service().cancel()


def _list_uav_mission_templates() -> list[dict[str, object]]:
    from ..skills.uav_spectrum_sim.templates import list_templates
    return list_templates()


def _build_uav_plan(mission_id: str, template: str, landmark: str | None, altitude_m: float | None, expires_in_s: float):
    from ..skills.uav_spectrum_sim.contracts import build_mission_plan
    return build_mission_plan(mission_id, template, landmark, altitude_m, expires_in_s)


def _validate_uav_mission_plan(mission_id: str, template: str, landmark: str | None = None, altitude_m: float | None = None, expires_in_s: float = 120.0) -> dict:
    from ..skills.uav_spectrum_sim.mission import get_uav_mission_service
    plan = _build_uav_plan(mission_id, template, landmark, altitude_m, expires_in_s)
    service = get_uav_mission_service()
    decision = service._policy.validate(plan, service._status_reader())
    return {"plan": plan.model_dump(), "decision": decision.model_dump()}


def _execute_uav_mission_plan(mission_id: str, template: str, landmark: str | None = None, altitude_m: float | None = None, expires_in_s: float = 120.0) -> dict:
    from ..skills.uav_spectrum_sim.mission import get_uav_mission_service
    return get_uav_mission_service().execute_plan(_build_uav_plan(mission_id, template, landmark, altitude_m, expires_in_s))


def _get_uav_mission_events() -> list[dict]:
    from ..skills.uav_spectrum_sim.mission import get_uav_mission_service
    return get_uav_mission_service().recent_events()


async def _get_weather(city: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"https://wttr.in/{city}?format=j1",
                headers={"User-Agent": "SpectrumClaw/1.0"},
            )
            resp.raise_for_status()
            data = resp.json()
        current = data.get("current_condition", [{}])[0]
        import json
        return json.dumps({
            "city": city,
            "temperature_c": current.get("temp_C"),
            "humidity": current.get("humidity"),
            "weather_desc": (current.get("weatherDesc", [{}])[0] or {}).get("value"),
            "wind_speed_kmph": current.get("windspeedKmph"),
            "feels_like_c": current.get("FeelsLikeC"),
        }, ensure_ascii=False)
    except Exception as exc:
        import json
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


async def _web_search(query: str, max_results: int = 5) -> str:
    import os, json
    key = os.getenv("TAVILY_API_KEY", "")
    if not key:
        return json.dumps({"error": "web_search 未配置 TAVILY_API_KEY"})
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                "https://api.tavily.com/search",
                json={"api_key": key, "query": query, "max_results": max_results, "search_depth": "basic"},
            )
            resp.raise_for_status()
            data = resp.json()
        results = data.get("results", [])
        lines = [f"搜索: {query}\n"]
        for i, r in enumerate(results, 1):
            lines.append(f"[{i}] {r.get('title','')}\n    URL: {r.get('url','')}\n    {r.get('content','')}\n")
        return "\n".join(lines)
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


async def _web_fetch(url: str) -> str:
    import re, json
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "SpectrumClaw/1.0"})
            resp.raise_for_status()
            text = resp.text
        if "text/html" in resp.headers.get("content-type", ""):
            text = re.sub(r"<(script|style)[^>]*>[\s\S]*?</\1>", " ", text, flags=re.IGNORECASE)
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
        return text[:4000] if len(text) > 4000 else text
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


async def _plan_frequency(band: str, region: str = "", service: str = "") -> str:
    import json
    try:
        from backend.skills.frequency_planning.planner import FrequencyPlanner
        planner = FrequencyPlanner()
        result = await planner.analyze(band, region=region, service=service)
        return json.dumps(result.to_dict(), ensure_ascii=False)
    except ImportError:
        from ..skills.frequency_planning.planner import FrequencyPlanner
        planner = FrequencyPlanner()
        result = await planner.analyze(band, region=region, service=service)
        return json.dumps(result.to_dict(), ensure_ascii=False)


async def _search_knowledge_base(query: str, top_k: int = 5) -> str:
    import json
    from pathlib import Path

    # Try new RAG pipeline first (Chroma + embeddings)
    chroma_dir = Path(__file__).resolve().parents[2] / "data" / "chroma"
    if (chroma_dir / "chroma.sqlite3").exists():
        try:
            from ..rag.graph.workflow import run_rag_query
            result = await run_rag_query(query)
            if result.get("answer") and not result.get("error"):
                citations = result.get("citations", [])
                cite_lines = []
                for i, c in enumerate(citations[:top_k], 1):
                    src = c.get("source", "?")
                    if isinstance(src, str) and "/" in src:
                        src = src.rsplit("/", 1)[-1]
                    cite_lines.append(
                        f"[{i}] {src} "
                        f"(p.{c.get('page', '?')}, relevance={c.get('relevance', 0):.3f})"
                    )
                debug = result.get("debug", {})
                # Return the RAG-generated answer (grounded in retrieved ITU-R
                # content) plus its sources, so the agent reasons over the actual
                # findings rather than just a list of document names.
                return (
                    f'知识库检索结果（embedding+Chroma，命中 '
                    f"{debug.get('packed_blocks', 0)} 个相关块）:\n\n"
                    f"{result['answer']}\n\n"
                    f"参考来源:\n" + "\n".join(cite_lines)
                )
        except Exception:
            pass  # fall through to TF-IDF

    # Fallback: legacy TF-IDF
    try:
        from ..knowledge.retrieve import search, is_ready
    except ImportError:
        from backend.knowledge.retrieve import search, is_ready
    if not is_ready():
        return json.dumps({"error": "知识库尚未索引"})
    results = search(query, top_k)
    if not results:
        return json.dumps({"message": "未找到相关内容"})
    lines = [f'知识库检索(TF-IDF): "{query}" — {len(results)} 条\n']
    for i, r in enumerate(results, 1):
        lines.append(f"[{i}] {r['source']} (相关性: {r['score']})\n    {r['text'][:600]}")
    return "\n".join(lines)


# ── registry ──

TOOL_REGISTRY: dict[str, dict[str, Any]] = {}


def register(name: str, handler, description: str, parameters: dict, category: str = ""):
    TOOL_REGISTRY[name] = {
        "name": name,
        "handler": handler,
        "description": description,
        "parameters": parameters,
        "category": category,
    }


def get_schema(name: str) -> dict | None:
    entry = TOOL_REGISTRY.get(name)
    if not entry:
        return None
    return {"type": "function", "function": {
        "name": entry["name"],
        "description": entry["description"],
        "parameters": entry["parameters"],
    }}


def get_all_schemas() -> list[dict]:
    return [s for name in TOOL_REGISTRY if (s := get_schema(name))]


def get_schemas_for(names: list[str]) -> list[dict]:
    return [s for name in names if (s := get_schema(name))]


def get_handler(name: str):
    entry = TOOL_REGISTRY.get(name)
    return entry["handler"] if entry else None


# ── register all built-in tools ──

def register_all():
    if TOOL_REGISTRY:
        return  # already registered
    register("get_time", _get_current_time, "获取当前 UTC 时间和北京时间",
             {"type": "object", "properties": {}}, "time")
    register("get_system_status", _get_system_status, "获取 SpectrumClaw 系统各组件的运行状态",
             {"type": "object", "properties": {}}, "env")
    register("get_uav_simulation_status", _get_uav_simulation_status,
             "获取 PX4/Gazebo 无人机仿真的运行、相机和实时位姿状态（只读）",
             {"type": "object", "properties": {}}, "uav")
    register("control_uav_simulation", _control_uav_simulation,
             "控制当前 PX4/Gazebo 仿真无人机。仅允许 status、arm、takeoff、hover、land、return_to_launch；只针对仿真，起飞高度为 1–20 米。执行飞行动作前应先查询状态并确认用户意图。",
             {"type": "object", "properties": {
                 "action": {"type": "string", "enum": ["status", "arm", "takeoff", "hover", "land", "return_to_launch"], "description": "仿真动作"},
                 "altitude_m": {"type": "number", "minimum": 1, "maximum": 20, "description": "仅 takeoff 使用，单位米，默认 3"},
             }, "required": ["action"]}, "uav")
    register("get_uav_mission_status", _get_uav_mission_status,
             "读取无人机仿真任务适配层的状态、当前真实位姿和可执行任务（只读）。",
             {"type": "object", "properties": {}}, "uav")
    register("execute_uav_mission", _execute_uav_mission,
             "通过统一任务适配层控制 PX4/Gazebo 仿真。允许起飞悬停、降落、返航、四个安全航点导航和固定安全周界巡检；不得用于真实飞行器。网页遥控接管时会拒绝执行。",
             {"type": "object", "properties": {
                 "mission": {"type": "string", "enum": ["takeoff_and_hover", "hover", "land", "return_to_launch", "navigate_to_safe_landmark", "survey_safe_perimeter"], "description": "仿真任务"},
                 "altitude_m": {"type": "number", "minimum": 1, "maximum": 20, "description": "仅 takeoff_and_hover 使用，默认 3 米"},
                 "landmark": {"type": "string", "enum": ["north_gate", "south_gate", "east_gate", "west_gate"], "description": "仅 navigate_to_safe_landmark 使用；不接受原始坐标"},
             }, "required": ["mission"]}, "uav")
    register("cancel_uav_mission", _cancel_uav_mission,
             "取消当前无人机仿真任务并让 PX4 进入悬停。只针对 PX4/Gazebo 仿真。",
             {"type": "object", "properties": {}}, "uav")
    plan_properties = {
        "mission_id": {"type": "string", "minLength": 3, "maxLength": 96, "description": "本次任务的唯一标识"},
        "template": {"type": "string", "enum": ["takeoff_and_hover", "hover", "land", "return_to_launch", "inspect_safe_perimeter", "collect_camera_evidence", "search_safe_route"], "description": "预审任务模板"},
        "landmark": {"type": "string", "enum": ["north_gate", "south_gate", "east_gate", "west_gate"], "description": "仅地标画面采集任务使用"},
        "altitude_m": {"type": "number", "minimum": 1, "maximum": 20, "description": "仅起飞悬停任务可选"},
        "expires_in_s": {"type": "number", "minimum": 5, "maximum": 600, "default": 120, "description": "计划有效期（秒）"},
    }
    register("list_uav_mission_templates", _list_uav_mission_templates,
             "列出可由智能体执行的固定安全任务模板。", {"type": "object", "properties": {}}, "uav")
    register("validate_uav_mission_plan", _validate_uav_mission_plan,
             "验证声明式无人机任务计划；只读，不会控制飞行器。", {"type": "object", "properties": plan_properties, "required": ["mission_id", "template"]}, "uav")
    register("execute_uav_mission_plan", _execute_uav_mission_plan,
             "执行已验证的声明式无人机任务计划。仅仿真；网页手动接管时会拒绝。", {"type": "object", "properties": plan_properties, "required": ["mission_id", "template"]}, "uav")
    register("get_uav_mission_events", _get_uav_mission_events,
             "读取无人机任务的公开审计事件，不包含隐藏推理。", {"type": "object", "properties": {}}, "uav")
    register("get_weather", _get_weather, "查询指定城市的实时天气信息（温度、湿度、风速等）",
             {"type": "object", "properties": {"city": {"type": "string", "description": "城市名称"}},
              "required": ["city"]}, "weather")
    register("web_search", _web_search, "搜索互联网获取实时信息",
             {"type": "object", "properties": {
                 "query": {"type": "string", "description": "搜索关键词"},
                 "max_results": {"type": "integer", "description": "最大结果数", "default": 5},
             }, "required": ["query"]}, "web")
    register("web_fetch", _web_fetch, "抓取指定 URL 的网页内容并返回纯文本",
             {"type": "object", "properties": {"url": {"type": "string", "description": "网页 URL"}},
              "required": ["url"]}, "web")
    register("search_knowledge_base", _search_knowledge_base,
             "搜索本地 ITU 频谱知识库（803 份 ITU-R 建议书、报告、无线电规则）",
             {"type": "object", "properties": {
                 "query": {"type": "string", "description": "搜索关键词"},
                 "top_k": {"type": "integer", "description": "返回结果数", "default": 5},
             }, "required": ["query"]}, "knowledge")
    register("plan_frequency", _plan_frequency,
             "查询特定频段在指定区域的频率划分——返回分配的业务、限制条件、相关脚注和标准",
             {"type": "object", "properties": {
                 "band": {"type": "string", "description": "频率范围，如 2300-2400 MHz"},
                 "region": {"type": "string", "description": "ITU Region (Region 1/2/3) 或国家名"},
                 "service": {"type": "string", "description": "业务类型，如 Mobile/Fixed/Satellite"},
             }, "required": ["band"]}, "knowledge")
