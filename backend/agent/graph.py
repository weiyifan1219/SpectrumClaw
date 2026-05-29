"""LangGraph StateGraph definition for SpectrumClaw agent loop."""

from __future__ import annotations

from langgraph.graph import StateGraph, END
from .state import AgentState
from .nodes import (
    router_node,
    rag_search_node,
    tool_executor_node,
    llm_answer_node,
    web_search_node,
    finalizer_node,
)


def route_after_router(state: AgentState) -> str:
    intent = state.get("user_intent", "chat")
    mapping = {
        "rag": "rag_search",
        "tool": "tool_executor",
        "web": "web_search",
        "chat": "llm_answer",
    }
    return mapping.get(intent, "llm_answer")


def route_after_rag(state: AgentState) -> str:
    return "llm_answer"


def route_after_tool(state: AgentState) -> str:
    return "llm_answer"


def route_after_web(state: AgentState) -> str:
    return "llm_answer"


def build_graph() -> StateGraph:
    workflow = StateGraph(AgentState)

    workflow.add_node("router", router_node)
    workflow.add_node("rag_search", rag_search_node)
    workflow.add_node("tool_executor", tool_executor_node)
    workflow.add_node("web_search", web_search_node)
    workflow.add_node("llm_answer", llm_answer_node)
    workflow.add_node("finalizer", finalizer_node)

    workflow.set_entry_point("router")

    workflow.add_conditional_edges("router", route_after_router, {
        "rag_search": "rag_search",
        "tool_executor": "tool_executor",
        "web_search": "web_search",
        "llm_answer": "llm_answer",
    })
    workflow.add_edge("rag_search", "llm_answer")
    workflow.add_edge("tool_executor", "llm_answer")
    workflow.add_edge("web_search", "llm_answer")
    workflow.add_edge("llm_answer", "finalizer")
    workflow.add_edge("finalizer", END)

    return workflow.compile()


# singleton
_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph
