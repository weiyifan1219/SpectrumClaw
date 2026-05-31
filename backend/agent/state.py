"""AgentState — shared state flowing through LangGraph nodes."""

from __future__ import annotations

from operator import add
from typing import Annotated, Any, TypedDict


class AgentState(TypedDict, total=False):
    messages: list[dict[str, Any]]
    user_intent: str
    selected_skill: str | None
    plan: list[str]
    tool_calls: list[dict[str, Any]]
    rag_results: list[dict[str, Any]]
    artifacts: list[dict[str, Any]]
    logs: Annotated[list[dict[str, Any]], add]
    reasoning: str
    thinking_events: list[str]
    final_answer: str
    error: str | None
    citations: list[str]
    model: str
    thinking_enabled: bool
    reasoning_effort: str | None
    tool_rounds: int
    provider: str
    api_type: str
    # memory fields
    thread_id: str
    user_id: str
    memory_hits: list[dict[str, Any]]
    memory_candidates: list[dict[str, Any]]
    skill_run: dict[str, Any] | None
    feedback_target_id: str | None
