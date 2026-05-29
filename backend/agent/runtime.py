"""Runtime selector: legacy (existing backend) vs langgraph (new agent graph).

Usage:
    from backend.agent.runtime import get_runtime
    runtime = get_runtime()
    async for event in runtime.stream_chat(messages, ...):
        ...
"""

from __future__ import annotations

from typing import Any, AsyncIterator

from ..config import get_settings


def get_runtime() -> str:
    """Return configured runtime mode."""
    return get_settings().agent_runtime


async def stream_chat_legacy(
    messages: list[dict[str, Any]],
    provider_override: str | None = None,
    model_override: str | None = None,
    thinking_enabled: bool = False,
    reasoning_effort: str | None = None,
    tool_names: list[str] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Delegate to legacy stream_chat."""
    from ..llm.client import stream_chat
    async for event in stream_chat(
        messages,
        provider_override=provider_override,
        model_override=model_override,
        thinking_enabled=thinking_enabled,
        reasoning_effort=reasoning_effort,
        tool_names=tool_names,
    ):
        yield event


async def stream_chat_langgraph(
    messages: list[dict[str, Any]],
    provider_override: str | None = None,
    model_override: str | None = None,
    thinking_enabled: bool = False,
    reasoning_effort: str | None = None,
    tool_names: list[str] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Run agent through LangGraph StateGraph, yield SSE events."""
    from .graph import get_graph
    from . import events

    settings = get_settings()
    provider = settings.provider_profile(provider_override, model_override)

    initial_state = {
        "messages": messages,
        "user_intent": "",
        "selected_skill": None,
        "plan": [],
        "tool_calls": [],
        "rag_results": [],
        "artifacts": [],
        "logs": [],
        "reasoning": "",
        "thinking_events": [],
        "final_answer": "",
        "error": None,
        "citations": [],
        "model": provider.model,
        "thinking_enabled": thinking_enabled,
        "reasoning_effort": reasoning_effort,
        "tool_rounds": 0,
        "provider": provider.provider,
        "api_type": provider.api_type,
    }

    graph = get_graph()

    yield events.thinking("Agent 初始化完成，开始分析你的问题…")

    try:
        final_state = await graph.ainvoke(initial_state)
        answer = final_state.get("final_answer", "")
        citations = final_state.get("citations", [])

        # stream the answer as content event
        yield events.content(answer)

        meta = {
            "configured": True,
            "provider": provider.provider,
            "api_type": provider.api_type,
            "model": provider.model,
            "thinking_enabled": thinking_enabled,
            "reasoning_effort": reasoning_effort,
            "citations": citations,
            "tool_rounds": final_state.get("tool_rounds", 0),
        }
        yield events.done(meta)

    except Exception as exc:
        yield events.error(str(exc))


async def stream_chat(
    messages: list[dict[str, Any]],
    provider_override: str | None = None,
    model_override: str | None = None,
    thinking_enabled: bool = False,
    reasoning_effort: str | None = None,
    tool_names: list[str] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Unified streaming entry point. Dispatches to legacy or langgraph based on config."""
    runtime = get_runtime()
    if runtime == "langgraph":
        async for event in stream_chat_langgraph(
            messages, provider_override, model_override,
            thinking_enabled, reasoning_effort, tool_names,
        ):
            yield event
    else:
        async for event in stream_chat_legacy(
            messages, provider_override, model_override,
            thinking_enabled, reasoning_effort, tool_names,
        ):
            yield event
