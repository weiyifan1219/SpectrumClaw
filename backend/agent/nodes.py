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


# ── RAG node (LangChain retriever) ──

async def rag_search_node(state: AgentState) -> dict[str, Any]:
    from ..rag.retriever import get_retriever
    from ..rag.citations import rag_context, format_citations

    last_user = ""
    for m in reversed(state.get("messages", [])):
        if m.get("role") == "user":
            last_user = str(m.get("content", ""))
            break

    # Try new RAG pipeline first (Chroma embedding-based)
    new_rag_ctx = None
    new_citations = []
    try:
        from ..rag.graph.workflow import run_rag_query
        rag_result = await run_rag_query(last_user)
        if rag_result.get("answer") and not rag_result.get("error"):
            ctx = rag_result.get("debug", {}).get("final_context", "")
            if not ctx:
                ctx_parts = []
                for c in rag_result.get("citations", []):
                    ctx_parts.append(
                        f"[来源] {c.get('source', '?')} (p.{c.get('page', '?')}, "
                        f"relevance={c.get('relevance', 0):.3f})"
                    )
                ctx = "\n".join(ctx_parts) if ctx_parts else ""
            if ctx:
                new_rag_ctx = (
                    f'知识库检索: "{last_user}"\n\n'
                    f"{ctx}\n\n"
                    f"请基于以上知识库内容回答用户问题。如果知识库中没有相关信息，请如实说明。"
                )
                new_citations = [
                    f"{c.get('source', '?')} (p.{c.get('page', '?')})"
                    for c in rag_result.get("citations", [])
                ]
            if new_rag_ctx:
                msgs = list(state.get("messages", []))
                msgs.append({"role": "system", "content": new_rag_ctx})
                return {
                    "rag_results": [
                        {"source": c.get("source", ""), "text": "", "score": c.get("relevance", 0)}
                        for c in rag_result.get("citations", [])
                    ],
                    "citations": new_citations,
                    "messages": msgs,
                    "logs": [{"node": "rag_search", "results": len(new_citations), "backend": "RAG Pipeline (Chroma+embedding)"}],
                }
    except Exception:
        pass  # fall through to legacy TF-IDF

    # Fallback: legacy TF-IDF retriever
    retriever = get_retriever(top_k=5)
    docs = await retriever.ainvoke(last_user)
    citations = [d.metadata.get("source", "") for d in docs]
    ctx = rag_context(docs, last_user)
    msgs = list(state.get("messages", []))
    msgs.append({"role": "system", "content": ctx})

    return {
        "rag_results": [{"source": d.metadata.get("source", ""), "text": d.page_content[:600], "score": d.metadata.get("score", 0)} for d in docs],
        "citations": citations,
        "messages": msgs,
        "logs": [{"node": "rag_search", "results": len(docs), "backend": "TF-IDF (fallback)"}],
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

    # Use LangChain StructuredTool when available
    if any(k in last_user for k in ["几点", "时间", "time"]):
        from ..tools.langchain_tools import build_langchain_tool
        lc_tool = build_langchain_tool("get_time")
        if lc_tool:
            result = await lc_tool.ainvoke({})
            ctx = f"[工具结果] 当前时间: {result}"
            msgs = list(state.get("messages", []))
            msgs.append({"role": "system", "content": ctx})
            return {"messages": msgs, "logs": [{"node": "tool_executor", "tool": "get_time", "backend": "LangChain"}]}

    if any(k in last_user for k in ["系统状态", "status"]):
        from ..tools.langchain_tools import build_langchain_tool
        lc_tool = build_langchain_tool("get_system_status")
        if lc_tool:
            result = await lc_tool.ainvoke({})
            ctx = f"[工具结果] 系统状态: {_json.dumps(result, ensure_ascii=False)}"
            msgs = list(state.get("messages", []))
            msgs.append({"role": "system", "content": ctx})
            return {"messages": msgs, "logs": [{"node": "tool_executor", "tool": "get_system_status", "backend": "LangChain"}]}

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
