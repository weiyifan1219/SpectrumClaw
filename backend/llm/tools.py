"""SpectrumClaw tool registry. Tools are provider-agnostic — registered once, usable across all LLM backends."""

from datetime import datetime, timezone

import httpx

# ── built-in tool handlers ──


def _get_current_time() -> str:
    """Return current UTC and Beijing time."""
    utc = datetime.now(timezone.utc)
    bj = utc.strftime("%Y-%m-%dT%H:%M:%S+08:00")  # Beijing is UTC+8 via manual offset
    return f"UTC: {utc.strftime('%Y-%m-%dT%H:%M:%SZ')} | Beijing: {bj}"


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


async def _web_fetch(url: str) -> str:
    """Fetch a URL and return extracted text content (limited to ~4000 chars)."""
    if not url.startswith(("http://", "https://")):
        return json_dumps({"error": "url must start with http:// or https://"})

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(
                url,
                headers={
                    "User-Agent": "SpectrumClaw/1.0 (spectrum-agent; web-fetch-tool)",
                    "Accept": "text/html,text/plain,application/json",
                },
            )
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            text = resp.text

            # basic HTML → plain text extraction (strip tags)
            if "text/html" in content_type:
                text = _html_to_text(text)

            # truncate
            if len(text) > 4000:
                text = text[:4000] + "\n\n[内容已截断，完整内容请直接访问源 URL]"

            return text

    except httpx.HTTPStatusError as exc:
        return json_dumps({"error": f"HTTP {exc.response.status_code}"})
    except httpx.TimeoutException:
        return json_dumps({"error": "请求超时 (15s)"})
    except Exception as exc:
        return json_dumps({"error": str(exc)})


async def _search_web(query: str) -> str:
    """Search the web using DuckDuckGo and return top results."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://lite.duckduckgo.com/lite/",
                params={"q": query},
                headers={
                    "User-Agent": "SpectrumClaw/1.0 (spectrum-agent; web-search)",
                    "Accept": "text/html",
                },
            )
            resp.raise_for_status()
            # extract result snippets from DuckDuckGo Lite HTML
            text = _html_to_text(resp.text, strip_all=False)

            # return first ~2000 chars of search result text
            if len(text) > 2000:
                text = text[:2000] + "\n\n[搜索内容已截断]"

            return text or json_dumps({"message": "未找到相关搜索结果"})

    except Exception as exc:
        return json_dumps({"error": str(exc)})


# ── helpers ──


def json_dumps(obj: dict) -> str:
    import json as _json
    return _json.dumps(obj, ensure_ascii=False)


def _html_to_text(html: str, strip_all: bool = True) -> str:
    """Crude HTML → plain text: remove script/style tags and strip remaining tags."""
    import re
    # remove script & style blocks
    html = re.sub(r"<(script|style)[^>]*>[\s\S]*?</\1>", " ", html, flags=re.IGNORECASE)
    # replace block-level tags with newlines
    html = re.sub(r"</?(?:br|p|div|tr|h\d|li|article|section)[^>]*>", "\n", html, flags=re.IGNORECASE)
    # strip all remaining tags
    clean = re.sub(r"<[^>]+>", " ", html)
    # decode entities
    clean = clean.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&#x27;", "'").replace("&nbsp;", " ")
    if strip_all:
        # collapse whitespace
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
        "name": "web_fetch",
        "description": "抓取指定 URL 的网页内容，返回提取的纯文本。用于获取实时信息、查天气、读新闻、看文档等。",
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
        "name": "search_web",
        "description": "搜索互联网，返回相关结果摘要。用于查找实时信息、新闻、技术文档等。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词，用中文或英文",
                },
            },
            "required": ["query"],
        },
        "handler": _search_web,
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
