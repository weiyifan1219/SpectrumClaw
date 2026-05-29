"""LangGraph node implementations — all delegate to existing legacy backend modules."""

from __future__ import annotations

import asyncio
from typing import Any

from .state import AgentState

# ── shared helpers ──


async def _run_legacy_chat(state: AgentState) -> tuple[str, dict[str, Any]]:
    """Call existing legacy chat() to keep tool/LLM behavior unchanged."""
    from ..llm.client import chat
    from ..config import get_settings

    settings = get_settings()
    provider = settings.provider_profile(
        state.get("model"),
        state.get("model"),
    )

    reply, meta = await chat(
        state["messages"],
        provider_override=provider.provider,
        model_override=provider.model,
        thinking_enabled=state.get("thinking_enabled", False),
        reasoning_effort=state.get("reasoning_effort"),
        tool_names=None,  # tools handled by graph routing
    )
    return reply, meta


# ── nodes ──


async def router_node(state: AgentState) -> dict[str, Any]:
    """Classify user intent: chat / rag / tool / web / skill."""
    last_msg = ""
    for m in reversed(state.get("messages", [])):
        if m.get("role") == "user":
            last_msg = str(m.get("content", "")).lower()
            break

    # keyword-based routing (to be replaced with LLM-based router)
    kb_keywords = ["itu", "建议书", "rec.", "recommendation", "无线电规则", "频谱", "频段", "干扰",
                   "分配", "regulation", "frequency", "vhf", "uhf", "hf", "mhz", "ghz"]
    web_keywords = ["天气", "新闻", "最新", "搜索", "查询", "weather", "news", "search"]
    tool_keywords = ["几点", "时间", "系统状态", "time", "status"]

    if any(k in last_msg for k in kb_keywords):
        return {"user_intent": "rag"}
    if any(k in last_msg for k in tool_keywords):
        return {"user_intent": "tool"}
    if any(k in last_msg for k in web_keywords):
        return {"user_intent": "web"}

    return {"user_intent": "chat"}


async def rag_search_node(state: AgentState) -> dict[str, Any]:
    """Search ITU knowledge base."""
    from ..knowledge.retrieve import search
    last_user = ""
    for m in reversed(state.get("messages", [])):
        if m.get("role") == "user":
            last_user = str(m.get("content", ""))
            break
    results = search(last_user, top_k=5)
    citations = [r.get("source", "") for r in results]
    return {"rag_results": results, "citations": citations}


async def tool_executor_node(state: AgentState) -> dict[str, Any]:
    """Execute built-in tools via registry."""
    from ..llm.client import get_tool_schemas, _execute_tools, TOOL_REGISTRY
    return {"tool_rounds": state.get("tool_rounds", 0)}


async def llm_answer_node(state: AgentState) -> dict[str, Any]:
    """Generate final answer using legacy chat()."""
    reply, meta = await _run_legacy_chat(state)
    return {
        "final_answer": reply,
        "provider": meta.get("provider", ""),
        "api_type": meta.get("api_type", ""),
        "tool_rounds": meta.get("tool_rounds", 0),
    }


async def web_search_node(state: AgentState) -> dict[str, Any]:
    """Proxy to web search tool via legacy tool executor."""
    from ..llm.client import TOOL_REGISTRY, get_tool_schemas
    return {"user_intent": "web"}


async def finalizer_node(state: AgentState) -> dict[str, Any]:
    """Normalize final output: ensure final_answer is populated."""
    answer = state.get("final_answer", "")
    if not answer:
        # fallback: grab last assistant message
        for m in reversed(state.get("messages", [])):
            if m.get("role") == "assistant" and m.get("content"):
                answer = str(m["content"])
                break
    return {
        "final_answer": answer or "模型返回为空。",
        "citations": state.get("citations", []),
        "logs": state.get("logs", []),
    }
