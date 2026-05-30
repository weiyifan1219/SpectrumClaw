"""LangGraph RAG workflow — compile and run the full retrieval + generation pipeline."""

from __future__ import annotations

from langgraph.graph import StateGraph, END

from .state import RAGState
from .nodes import (
    analyze_query_node,
    retrieve_vector_node,
    retrieve_keyword_node,
    retrieve_graph_node,
    rerank_results_node,
    pack_context_node,
    analyze_retrieved_images_node,
    generate_answer_node,
)


def build_rag_graph() -> StateGraph:
    workflow = StateGraph(RAGState)

    workflow.add_node("analyze_query", analyze_query_node)
    workflow.add_node("retrieve_vector", retrieve_vector_node)
    workflow.add_node("retrieve_keyword", retrieve_keyword_node)
    workflow.add_node("retrieve_graph", retrieve_graph_node)
    workflow.add_node("rerank_results", rerank_results_node)
    workflow.add_node("pack_context", pack_context_node)
    workflow.add_node("analyze_images", analyze_retrieved_images_node)
    workflow.add_node("generate_answer", generate_answer_node)

    workflow.set_entry_point("analyze_query")
    workflow.add_edge("analyze_query", "retrieve_vector")
    workflow.add_edge("analyze_query", "retrieve_keyword")
    workflow.add_edge("analyze_query", "retrieve_graph")
    workflow.add_edge("retrieve_vector", "rerank_results")
    workflow.add_edge("retrieve_keyword", "rerank_results")
    workflow.add_edge("retrieve_graph", "rerank_results")
    workflow.add_edge("rerank_results", "pack_context")
    workflow.add_edge("pack_context", "analyze_images")
    workflow.add_edge("analyze_images", "generate_answer")
    workflow.add_edge("generate_answer", END)

    return workflow.compile()


# singleton
_rag_graph = None


def get_rag_graph():
    global _rag_graph
    if _rag_graph is None:
        _rag_graph = build_rag_graph()
    return _rag_graph


async def run_rag_query(question: str) -> dict:
    """Run the full RAG pipeline and return answer + debug info."""
    graph = get_rag_graph()
    result = await graph.ainvoke({"question": question})

    return {
        "answer": result.get("answer", ""),
        "citations": result.get("citations", []),
        "debug": result.get("debug", {}),
        "error": result.get("error"),
    }
