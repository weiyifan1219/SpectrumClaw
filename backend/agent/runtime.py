"""Runtime selector: legacy (existing backend) vs langgraph (new agent graph)."""

from __future__ import annotations

from typing import Any, AsyncIterator


def get_runtime() -> str:
    from ..config import get_settings
    runtime = (get_settings().agent_runtime or "legacy").strip().lower()
    return runtime if runtime in {"legacy", "langgraph"} else "legacy"


def _tool_names_for_intent(intent: str, requested: list[str] | None = None) -> list[str] | None:
    defaults = {
        "rag": ["search_knowledge_base"],
        "tool": ["get_time", "get_system_status"],
        "web": ["web_search", "web_fetch", "get_weather"],
    }
    names = defaults.get(intent)
    if not names:
        return None
    if requested is None:
        return names
    selected = [name for name in names if name in requested]
    return selected or None


# ── legacy path (unchanged) ──

async def stream_chat_legacy(
    messages: list[dict[str, Any]],
    provider_override: str | None = None,
    model_override: str | None = None,
    thinking_enabled: bool = False,
    reasoning_effort: str | None = None,
    tool_names: list[str] | None = None,
    thread_id: str = "",
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
    thread_id: str = "",
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

    import uuid
    tid = thread_id or f"thread_{uuid.uuid4().hex[:12]}"

    # ── memory reader (non-blocking, best-effort) ──
    memory_hits: list[dict[str, Any]] = []
    if settings.memory_enabled:
        try:
            from ..memory.service import MemoryService
            mem_svc = MemoryService(db_path=settings.memory_db_path)
            last_user = ""
            for m in reversed(messages):
                if m.get("role") == "user":
                    last_user = str(m.get("content", ""))
                    break
            mem_items = mem_svc.search_memories(thread_id=tid, limit=settings.memory_inject_top_k)
            thread = mem_svc.store.get_thread(tid)
            thread_summary = thread.summary if thread and thread.summary else ""
            memory_hits = [
                {"kind": item.kind, "summary": item.summary, "text": item.text, "tags": item.tags}
                for item in mem_items
            ]
            if thread_summary:
                memory_hits.insert(0, {"kind": "thread_summary", "summary": thread_summary, "text": "", "tags": []})
        except Exception:
            pass

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
        "thread_id": tid,
        "user_id": "local_user",
        "memory_hits": memory_hits,
        "memory_candidates": [],
        "skill_run": None,
        "feedback_target_id": None,
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
        answer_tool_names = _tool_names_for_intent(intent, tool_names)
        done_event = None

        async for event in stream_chat_legacy(
            augmented_msgs,
            provider_override=provider.provider,
            model_override=provider.model,
            thinking_enabled=thinking_enabled,
            reasoning_effort=reasoning_effort,
            tool_names=answer_tool_names,
        ):
            if event.get("type") == "done":
                done_event = event
            else:
                yield event

        # ── phase 3: finalize ──
        _merge_state_update(final_state, await finalizer_node(final_state))

        # ── phase 4: memory writer (best-effort, never blocks response) ──
        if settings.memory_enabled:
            _write_memory(final_state, tid, provider.model)

        # Patch the done event with graph metadata BEFORE yielding
        if done_event is not None:
            done_event["data"]["graph_nodes"] = nodes_run
            done_event["data"]["citations"] = final_state.get("citations", [])
            done_event["data"]["runtime"] = "langgraph"
            done_event["data"]["rag_results"] = final_state.get("rag_results", [])
            done_event["data"]["thread_id"] = tid
            yield done_event
        else:
            yield events.done({
                "configured": True,
                "provider": provider.provider,
                "api_type": provider.api_type,
                "model": provider.model,
                "graph_nodes": nodes_run,
                "citations": final_state.get("citations", []),
                "rag_results": final_state.get("rag_results", []),
                "runtime": "langgraph",
                "thread_id": tid,
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


def _write_memory(state: dict[str, Any], thread_id: str, model: str) -> None:
    """Best-effort memory persistence. Failures are silently ignored."""
    try:
        from ..config import get_settings
        from ..memory.service import MemoryService

        settings = get_settings()
        mem = MemoryService(db_path=settings.memory_db_path)

        # ensure thread record
        mem.ensure_thread(thread_id)
        mem.bump_thread(thread_id)

        # record user + assistant events
        for m in state.get("messages", []):
            role = m.get("role", "")
            content = str(m.get("content", ""))[:2000]
            if role in ("user", "assistant") and content:
                mem.record_event(
                    thread_id=thread_id,
                    event_type=role,
                    role=role,
                    content=content,
                    metadata={"model": model},
                )

        # record RAG query as episodic memory
        rag_results = state.get("rag_results", [])
        if rag_results:
            last_user = ""
            for m in reversed(state.get("messages", [])):
                if m.get("role") == "user":
                    last_user = str(m.get("content", ""))
                    break
            mem.add_memory(
                text=f"RAG查询: {last_user[:300]} — 返回 {len(rag_results)} 条结果",
                kind="episodic",
                thread_id=thread_id,
                tags=["rag"],
                confidence=0.7,
            )

        # record skill_run if present
        skill_run = state.get("skill_run")
        if skill_run and isinstance(skill_run, dict):
            mem.record_skill_run(
                skill_name=skill_run.get("skill_name", "unknown"),
                thread_id=thread_id,
                status=skill_run.get("status", "success"),
                output_summary=skill_run.get("output_summary", ""),
                latency_ms=skill_run.get("latency_ms", 0),
                error=skill_run.get("error", ""),
            )
    except Exception:
        pass


# ── unified entry ──

async def stream_chat(
    messages: list[dict[str, Any]],
    provider_override: str | None = None,
    model_override: str | None = None,
    thinking_enabled: bool = False,
    reasoning_effort: str | None = None,
    tool_names: list[str] | None = None,
    thread_id: str = "",
) -> AsyncIterator[dict[str, Any]]:
    runtime = get_runtime()
    if runtime == "langgraph":
        async for event in stream_chat_langgraph(
            messages, provider_override, model_override,
            thinking_enabled, reasoning_effort, tool_names,
            thread_id=thread_id,
        ):
            yield event
    else:
        async for event in stream_chat_legacy(
            messages, provider_override, model_override,
            thinking_enabled, reasoning_effort, tool_names,
            thread_id=thread_id,
        ):
            yield event
