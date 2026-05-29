"""Runtime selector: legacy (existing backend) vs langgraph (new agent graph)."""

from __future__ import annotations

from typing import Any, AsyncIterator


def get_runtime() -> str:
    from ..config import get_settings
    runtime = (get_settings().agent_runtime or "legacy").strip().lower()
    return runtime if runtime in {"legacy", "langgraph"} else "legacy"


# ── legacy path (unchanged) ──

async def stream_chat_legacy(
    messages: list[dict[str, Any]],
    provider_override: str | None = None,
    model_override: str | None = None,
    thinking_enabled: bool = False,
    reasoning_effort: str | None = None,
    tool_names: list[str] | None = None,
) -> AsyncIterator[dict[str, Any]]:
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


# ── langgraph path ──

async def stream_chat_langgraph(
    messages: list[dict[str, Any]],
    provider_override: str | None = None,
    model_override: str | None = None,
    thinking_enabled: bool = False,
    reasoning_effort: str | None = None,
    tool_names: list[str] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    from . import events
    from .nodes import (
        finalizer_node,
        llm_answer_node,
        rag_search_node,
        router_node,
        tool_executor_node,
        web_search_node,
    )
    from ..config import get_settings
    from ..tools.registry import register_all

    settings = get_settings()
    provider = settings.provider_profile(provider_override, model_override)
    register_all()

    initial_state = {
        "messages": messages,
        "user_intent": "",
        "plan": [],
        "tool_calls": [],
        "rag_results": [],
        "artifacts": [],
        "logs": [],
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

    yield events.thinking("Agent 初始化…")

    try:
        final_state = dict(initial_state)

        router_update = await router_node(final_state)
        _merge_state_update(final_state, router_update)

        intent = final_state.get("user_intent", "chat")
        if intent == "rag":
            _merge_state_update(final_state, await rag_search_node(final_state))
        elif intent == "tool":
            _merge_state_update(final_state, await tool_executor_node(final_state))
        elif intent == "web":
            _merge_state_update(final_state, await web_search_node(final_state))

        _merge_state_update(final_state, await llm_answer_node(final_state))
        _merge_state_update(final_state, await finalizer_node(final_state))

        answer = final_state.get("final_answer", "")
        citations = final_state.get("citations", [])
        graph_logs = final_state.get("logs", [])

        # log the graph execution path
        nodes_run = [l.get("node", "?") for l in graph_logs]
        yield events.thinking(f"执行路径: {' → '.join(nodes_run)}")

        # stream the final answer
        yield events.content(answer)

        meta = {
            "configured": True,
            "provider": provider.provider,
            "api_type": provider.api_type,
            "model": provider.model,
            "thinking_enabled": thinking_enabled,
            "reasoning_effort": reasoning_effort,
            "citations": citations,
            "graph_nodes": nodes_run,
            "tool_rounds": final_state.get("tool_rounds", 0),
            "runtime": "langgraph",
        }
        yield events.done(meta)

    except Exception as exc:
        yield events.error(str(exc))


def _merge_state_update(state: dict[str, Any], update: dict[str, Any]) -> None:
    for key, value in update.items():
        if key == "logs":
            state.setdefault("logs", [])
            state["logs"].extend(value or [])
        else:
            state[key] = value


# ── unified entry ──

async def stream_chat(
    messages: list[dict[str, Any]],
    provider_override: str | None = None,
    model_override: str | None = None,
    thinking_enabled: bool = False,
    reasoning_effort: str | None = None,
    tool_names: list[str] | None = None,
) -> AsyncIterator[dict[str, Any]]:
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
