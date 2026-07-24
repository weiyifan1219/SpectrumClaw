"""SpectrumClaw tool registry. Tools are provider-agnostic — registered once, usable across all LLM backends.

Search backend: Tavily (https://tavily.com) — purpose-built for AI agents.
Free tier: 1000 searches/month. Set TAVILY_API_KEY in .env to enable.
"""

from datetime import datetime, timedelta, timezone

import httpx


# ── helpers ──

def _json(obj) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False)


# ── built-in sync handlers ──

def _get_current_time() -> str:
    utc = datetime.now(timezone.utc)
    bj = (utc + timedelta(hours=8)).strftime("%Y-%m-%dT%H:%M:%S+08:00")
    return f"UTC: {utc.strftime('%Y-%m-%dT%H:%M:%SZ')} | Beijing: {bj}"


def _get_system_status() -> dict:
    return {
        "frontend": "running (Vite dev server)",
        "backend": "running (FastAPI + uvicorn)",
        "llm": "connected",
        "skills": {
            "frequency_planning": "available",
            "spectrum_construction": "available",
            "resource_allocation": "available",
            "interference_analysis": "reserved",
            "modulation_recognition": "reserved",
        },
    }


def _uav_simulation_status() -> dict:
    from ..skills.uav_spectrum_sim.runtime import get_runtime_status
    status = get_runtime_status()
    return {
        "runtime": status["runtime"]["state"],
        "camera": status["runtime"]["camera"]["state"],
        "vehicle": status["runtime"]["camera"].get("vehicle", {}),
        "world": status["scene"]["vehicle"]["world"],
    }


def _uav_simulation_control(action: str, altitude_m: float | None = None) -> dict:
    """Control the allow-listed PX4 SITL actions; never a real aircraft."""
    from ..skills.uav_spectrum_sim.runtime import execute_vehicle_command
    return execute_vehicle_command(action, altitude_m)


def _uav_mission_status() -> dict:
    from ..skills.uav_spectrum_sim.mission import get_uav_mission_service
    return get_uav_mission_service().inspect()


def _execute_uav_mission(mission: str, altitude_m: float | None = None, landmark: str | None = None) -> dict:
    from ..skills.uav_spectrum_sim.mission import get_uav_mission_service
    return get_uav_mission_service().execute(mission, altitude_m, landmark)


def _cancel_uav_mission() -> dict:
    from ..skills.uav_spectrum_sim.mission import get_uav_mission_service
    return get_uav_mission_service().cancel()


def _get_tavily_key() -> str | None:
    """Read Tavily API key from config / env."""
    try:
        from ..config import get_settings
        s = get_settings()
        return getattr(s, "tavily_api_key", None) or None
    except Exception:
        import os
        return os.getenv("TAVILY_API_KEY")


# ── async handlers (web) ──

async def _web_search(query: str, max_results: int = 5) -> str:
    """Search the web using Tavily Search API."""
    key = _get_tavily_key()
    if not key:
        return _json({
            "error": "web_search 未配置 API key。请在 .env 中设置 TAVILY_API_KEY（免费注册: https://tavily.com）",
            "hint": "你也可以使用 web_fetch 工具直接抓取已知 URL"
        })

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": key,
                    "query": query,
                    "max_results": max_results,
                    "search_depth": "basic",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        results = data.get("results", [])
        if not results:
            return _json({"message": "未找到相关搜索结果", "query": query})

        lines = [f"搜索: {query}\n"]
        for i, r in enumerate(results, 1):
            title = r.get("title", "")
            url = r.get("url", "")
            content = r.get("content", "")
            lines.append(f"[{i}] {title}\n    URL: {url}\n    {content}\n")

        return "\n".join(lines)

    except httpx.HTTPStatusError as exc:
        return _json({"error": f"搜索 API 返回 {exc.response.status_code}"})
    except Exception as exc:
        return _json({"error": str(exc)})


async def _web_fetch(url: str) -> str:
    """Fetch a URL and return extracted text content."""
    if not url.startswith(("http://", "https://")):
        return _json({"error": "url must start with http:// or https://"})

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(
                url,
                headers={
                    "User-Agent": "SpectrumClaw/1.0 (AI-agent; web-fetch)",
                    "Accept": "text/html,text/plain,application/json",
                },
            )
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            text = resp.text

            if "text/html" in content_type:
                text = _strip_html(text)

            if len(text) > 4000:
                text = text[:4000] + "\n\n[内容已截断]"

            return text

    except httpx.HTTPStatusError as exc:
        return _json({"error": f"HTTP {exc.response.status_code}"})
    except httpx.TimeoutException:
        return _json({"error": "请求超时"})
    except Exception as exc:
        return _json({"error": str(exc)})


async def _get_weather(city: str) -> str:
    """Get current weather for a city using wttr.in."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"https://wttr.in/{city}?format=j1",
                headers={"User-Agent": "SpectrumClaw/1.0"},
            )
            resp.raise_for_status()
            data = resp.json()

        current = data.get("current_condition", [{}])[0]
        location = data.get("nearest_area", [{}])[0]

        return _json({
            "city": city,
            "temperature_c": current.get("temp_C"),
            "humidity": current.get("humidity"),
            "weather_desc": current.get("weatherDesc", [{}])[0].get("value"),
            "wind_speed_kmph": current.get("windspeedKmph"),
            "feels_like_c": current.get("FeelsLikeC"),
            "visibility_km": current.get("visibility"),
        })

    except Exception as exc:
        return _json({"error": str(exc)})


def _search_knowledge_base(query: str, top_k: int = 5) -> str:
    """Search the ITU spectrum knowledge base."""
    try:
        from ..knowledge.retrieve import search, is_ready
    except ImportError:
        from backend.knowledge.retrieve import search, is_ready

    if not is_ready():
        return _json({"error": "知识库尚未索引。请先运行: python -m backend.knowledge.ingest"})

    results = search(query, top_k)
    if not results:
        return _json({"message": "未找到相关内容", "query": query})

    lines = [f"知识库检索: \"{query}\" — 共 {len(results)} 条结果\n"]
    for i, r in enumerate(results, 1):
        lines.append(
            f"[{i}] 📄 {r['source']} (相关性: {r['score']})\n"
            f"    {r['text'][:600]}"
        )
    return "\n".join(lines)


def _strip_html(html: str) -> str:
    import re
    html = re.sub(r"<(script|style)[^>]*>[\s\S]*?</\1>", " ", html, flags=re.IGNORECASE)
    html = re.sub(r"</?(?:br|p|div|tr|h\d|li|article|section)[^>]*>", "\n", html, flags=re.IGNORECASE)
    clean = re.sub(r"<[^>]+>", " ", html)
    clean = clean.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&nbsp;", " ")
    clean = re.sub(r"[ \t]+", " ", clean)
    clean = re.sub(r"\n{3,}", "\n\n", clean)
    return clean.strip()


# ── tool registry ──

TOOLS = [
    {
        "name": "get_time",
        "description": "获取当前 UTC 时间和北京时间",
        "parameters": {"type": "object", "properties": {}},
        "handler": _get_current_time,
    },
    {
        "name": "get_system_status",
        "description": "获取 SpectrumClaw 系统各组件的运行状态",
        "parameters": {"type": "object", "properties": {}},
        "handler": _get_system_status,
    },
    {
        "name": "get_uav_simulation_status",
        "description": "获取当前 PX4/Gazebo 无人机仿真的运行、相机和实时位姿状态。只能读取仿真，不控制真实飞行器。",
        "parameters": {"type": "object", "properties": {}},
        "handler": _uav_simulation_status,
    },
    {
        "name": "control_uav_simulation",
        "description": "控制当前运行的 PX4/Gazebo 仿真无人机。仅允许 status、arm、takeoff、hover、land、return_to_launch；只针对仿真，起飞高度为 1–20 米。执行飞行动作前应先查询状态并确认用户意图。",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["status", "arm", "takeoff", "hover", "land", "return_to_launch"], "description": "仿真动作"},
                "altitude_m": {"type": "number", "minimum": 1, "maximum": 20, "description": "仅 takeoff 使用，单位米，默认 3"},
            },
            "required": ["action"],
        },
        "handler": _uav_simulation_control,
    },
    {
        "name": "get_uav_mission_status",
        "description": "读取无人机仿真任务适配层状态、真实位姿和允许的高层任务。只读。",
        "parameters": {"type": "object", "properties": {}},
        "handler": _uav_mission_status,
    },
    {
        "name": "execute_uav_mission",
        "description": "通过统一任务适配层控制 PX4/Gazebo 仿真。允许起飞悬停、降落、返航、固定安全航点导航和安全周界巡检；网页遥控接管时会拒绝执行，不能用于真实飞行器。",
        "parameters": {
            "type": "object",
            "properties": {
                "mission": {"type": "string", "enum": ["takeoff_and_hover", "hover", "land", "return_to_launch", "navigate_to_safe_landmark", "survey_safe_perimeter"], "description": "仿真任务"},
                "altitude_m": {"type": "number", "minimum": 1, "maximum": 20, "description": "仅 takeoff_and_hover 使用，默认 3 米"},
                "landmark": {"type": "string", "enum": ["north_gate", "south_gate", "east_gate", "west_gate"], "description": "仅 navigate_to_safe_landmark 使用；不接受原始坐标"},
            },
            "required": ["mission"],
        },
        "handler": _execute_uav_mission,
    },
    {
        "name": "cancel_uav_mission",
        "description": "取消当前无人机仿真任务并进入悬停。只针对 PX4/Gazebo 仿真。",
        "parameters": {"type": "object", "properties": {}},
        "handler": _cancel_uav_mission,
    },
    {
        "name": "get_weather",
        "description": "查询指定城市的实时天气信息（温度、湿度、风速等）",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "城市名称，支持中文（如 南京）或英文（如 Nanjing）",
                },
            },
            "required": ["city"],
        },
        "handler": _get_weather,
    },
    {
        "name": "web_search",
        "description": (
            "搜索互联网获取实时信息。当需要最新新闻、事件、数据、或你不知道的信息时使用。"
            "需要 TAVILY_API_KEY 环境变量（免费注册: https://tavily.com）"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词，用中文或英文。越具体越好。",
                },
                "max_results": {
                    "type": "integer",
                    "description": "最大返回结果数，默认 5",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
        "handler": _web_search,
    },
    {
        "name": "web_fetch",
        "description": "抓取指定 URL 的网页内容并返回纯文本。用于读取具体网页、文档、API 返回等。",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "要抓取的网页 URL，必须以 http:// 或 https:// 开头",
                },
            },
            "required": ["url"],
        },
        "handler": _web_fetch,
    },
    {
        "name": "search_knowledge_base",
        "description": (
            "搜索本地 ITU 频谱知识库（包含 ITU-R 建议书、报告、无线电规则）。"
            "用于查询频谱法规、频段分配、干扰标准、技术参数等专业问题。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词，用中文或英文。例如: VHF 频段分配, 干扰保护标准, 无线电规则 5.138",
                },
                "top_k": {
                    "type": "integer",
                    "description": "返回结果数量，默认 5",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
        "handler": _search_knowledge_base,
    },
]


def register_default_tools():
    from .client import register_tool
    for t in TOOLS:
        register_tool(t["name"], t["handler"], {
            "name": t["name"],
            "description": t["description"],
            "parameters": t["parameters"],
        })
    # also sync to unified tool registry
    try:
        from ..tools.registry import register_all
        register_all()
    except ImportError:
        pass
