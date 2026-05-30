"""RAGState — typed state flowing through the RAG LangGraph workflow."""

from __future__ import annotations

from operator import add
from typing import Annotated, Any, TypedDict


def _merge_debug(left: dict, right: dict) -> dict:
    """Merge two debug dicts, with right taking precedence."""
    return {**left, **right}


class RAGState(TypedDict, total=False):
    question: str
    query_info: dict[str, Any]
    vector_results: list[dict[str, Any]]
    keyword_results: list[dict[str, Any]]
    graph_results: list[dict[str, Any]]
    reranked_results: list[dict[str, Any]]
    final_context: str
    answer: str
    citations: list[dict[str, Any]]
    debug: Annotated[dict[str, Any], _merge_debug]
    error: str | None
