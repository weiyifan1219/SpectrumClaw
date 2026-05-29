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
        "logs": [],
        "rag_results": [],
        "citations": [],
        "model": provider.model,
        "thinking_enabled": thinking_enabled,
        "reasoning_effort": reasoning_effort,
        "tool_rounds": 0,
        "provider": provider.provider,
        "api_type": provider.api_type,
    }

    try:
        final_state = dict(initial_state)

        # ── phase 1: route and gather context (non-streaming) ──
        _merge_state_update(final_state, await router_node(final_state))
        intent = final_state.get("user_intent", "chat")

        if intent == "rag":
            _merge_state_update(final_state, await rag_search_node(final_state))
        elif intent == "tool":
            _merge_state_update(final_state, await tool_executor_node(final_state))
        elif intent == "web":
            _merge_state_update(final_state, await web_search_node(final_state))

        # short thinking: show what the agent decided
        nodes_run = [l.get("node", "?") for l in final_state.get("logs", [])]
        yield events.thinking(f"路由决策: {intent} → {' → '.join(nodes_run)}")

        # ── phase 2: stream the real LLM answer (token-by-token with reasoning) ──
        augmented_msgs = final_state.get("messages", messages)
        last_event = None

        async for event in stream_chat_legacy(
            augmented_msgs,
            provider_override=provider.provider,
            model_override=provider.model,
            thinking_enabled=thinking_enabled,
            reasoning_effort=reasoning_effort,
            tool_names=None,  # tools already handled by graph nodes
        ):
            last_event = event
            yield event

        # ── phase 3: finalize ──
        _merge_state_update(final_state, await finalizer_node(final_state))

        # patch the done event with graph metadata
        if last_event and last_event.get("type") == "done":
            last_event["data"]["graph_nodes"] = nodes_run
            last_event["data"]["citations"] = final_state.get("citations", [])
            last_event["data"]["runtime"] = "langgraph"
        else:
            yield events.done({
                "configured": True,
                "provider": provider.provider,
                "api_type": provider.api_type,
                "model": provider.model,
                "graph_nodes": nodes_run,
                "citations": final_state.get("citations", []),
                "runtime": "langgraph",
            })

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
