"""LangGraph node implementations — delegate to existing backend modules."""

from __future__ import annotations

import json as _json
from typing import Any

from .state import AgentState


# ── router ──

KB_KEYWORDS = [
    "itu", "建议书", "rec.", "recommendation", "无线电规则", "频谱", "频段", "干扰",
    "分配", "regulation", "frequency", "vhf", "uhf", "hf", "mhz", "ghz",
    "知识库", "标准", "规范", "protection criteria", "radio regulations",
]
WEB_KEYWORDS = ["天气", "新闻", "最新", "搜索", "查询", "weather", "news", "今天"]
TOOL_KEYWORDS = ["几点", "时间", "系统状态", "time", "status"]


async def router_node(state: AgentState) -> dict[str, Any]:
    last_msg = ""
    for m in reversed(state.get("messages", [])):
        if m.get("role") == "user":
            last_msg = str(m.get("content", "")).lower()
            break

    if any(k in last_msg for k in KB_KEYWORDS):
        return {"user_intent": "rag", "logs": [{"node": "router", "decision": "rag"}]}
    if any(k in last_msg for k in WEB_KEYWORDS):
        return {"user_intent": "web", "logs": [{"node": "router", "decision": "web"}]}
    if any(k in last_msg for k in TOOL_KEYWORDS):
        return {"user_intent": "tool", "logs": [{"node": "router", "decision": "tool"}]}
    return {"user_intent": "chat", "logs": [{"node": "router", "decision": "chat"}]}


# ── RAG node ──

async def rag_search_node(state: AgentState) -> dict[str, Any]:
    from ..knowledge.retrieve import search
    last_user = ""
    for m in reversed(state.get("messages", [])):
        if m.get("role") == "user":
            last_user = str(m.get("content", ""))
            break
    results = search(last_user, top_k=5)
    citations = [r.get("source", "") for r in results]

    # inject RAG results as a system context for the LLM
    ctx = "以下是从 ITU 知识库检索到的相关内容，请基于这些内容回答用户问题：\n\n"
    for i, r in enumerate(results, 1):
        ctx += f"[{i}] 📄 {r['source']} (相关性: {r['score']})\n{r['text'][:800]}\n\n"

    msgs = list(state.get("messages", []))
    msgs.append({"role": "system", "content": ctx})

    return {
        "rag_results": results,
        "citations": citations,
        "messages": msgs,
        "logs": [{"node": "rag_search", "results": len(results)}],
    }


# ── tool node ──

async def tool_executor_node(state: AgentState) -> dict[str, Any]:
    from ..tools.registry import get_handler, register_all

    register_all()

    last_user = ""
    for m in reversed(state.get("messages", [])):
        if m.get("role") == "user":
            last_user = str(m.get("content", ""))
            break

    # Find the right tool: if user asks for time, call get_time
    if any(k in last_user for k in ["几点", "时间", "time"]):
        handler = get_handler("get_time")
        if handler:
            result = handler()
            ctx = f"[工具结果] 当前时间: {result}"
            msgs = list(state.get("messages", []))
            msgs.append({"role": "system", "content": ctx})
            return {"messages": msgs, "logs": [{"node": "tool_executor", "tool": "get_time"}]}

    if any(k in last_user for k in ["系统状态", "status"]):
        handler = get_handler("get_system_status")
        if handler:
            result = handler()
            ctx = f"[工具结果] 系统状态: {_json.dumps(result, ensure_ascii=False)}"
            msgs = list(state.get("messages", []))
            msgs.append({"role": "system", "content": ctx})
            return {"messages": msgs, "logs": [{"node": "tool_executor", "tool": "get_system_status"}]}

    return {"logs": [{"node": "tool_executor", "tool": "none"}]}


# ── web node ──

async def web_search_node(state: AgentState) -> dict[str, Any]:
    from ..tools.registry import get_handler
    last_user = ""
    for m in reversed(state.get("messages", [])):
        if m.get("role") == "user":
            last_user = str(m.get("content", ""))
            break

    # try Tavily web search
    handler = get_handler("web_search")
    if handler:
        result = await handler(query=last_user, max_results=5)
        ctx = f"[工具结果] 网络搜索结果:\n{result}"
        msgs = list(state.get("messages", []))
        msgs.append({"role": "system", "content": ctx})
        return {"messages": msgs, "logs": [{"node": "web_search", "query": last_user}]}

    return {"logs": [{"node": "web_search", "error": "web_search handler not available"}]}


# ── LLM answer node ──

async def llm_answer_node(state: AgentState) -> dict[str, Any]:
    from ..llm.client import chat
    from ..config import get_settings

    settings = get_settings()
    provider = settings.provider_profile(
        state.get("provider") or None,
        state.get("model"),
    )

    reply, meta = await chat(
        state["messages"],
        provider_override=provider.provider,
        model_override=provider.model,
        thinking_enabled=state.get("thinking_enabled", False),
        reasoning_effort=state.get("reasoning_effort"),
        tool_names=None,
    )

    return {
        "final_answer": reply,
        "provider": meta.get("provider", ""),
        "api_type": meta.get("api_type", ""),
        "tool_rounds": meta.get("tool_rounds", 0),
        "logs": [{"node": "llm_answer", "model": provider.model}],
    }


# ── finalizer ──

async def finalizer_node(state: AgentState) -> dict[str, Any]:
    answer = state.get("final_answer", "")
    if not answer:
        for m in reversed(state.get("messages", [])):
            if m.get("role") == "assistant" and m.get("content"):
                answer = str(m["content"])
                break

    return {
        "final_answer": answer or "模型返回为空。",
        "citations": state.get("citations", []),
        "logs": [{"node": "finalizer", "answer_len": len(answer)}],
    }
