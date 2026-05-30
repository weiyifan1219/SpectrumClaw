"""LangGraph RAG node implementations."""

from __future__ import annotations

from typing import Any

from .state import RAGState
from ..retrievers.query_analyzer import SpectrumQueryAnalyzer
from ..retrievers.vector_retriever import VectorRetriever
from ..retrievers.keyword_retriever import KeywordRetriever
from ..retrievers.reranker import Reranker
from ..retrievers.context_packer import ContextPacker
from ..chains.answer_generator import AnswerGenerator


# ── shared component singletons (lazy init) ──

_query_analyzer: SpectrumQueryAnalyzer | None = None
_vector_retriever: VectorRetriever | None = None
_keyword_retriever: KeywordRetriever | None = None
_graph_retriever = None  # GraphRetriever | None
_reranker: Reranker | None = None
_context_packer: ContextPacker | None = None
_answer_generator: AnswerGenerator | None = None


def _get_analyzer() -> SpectrumQueryAnalyzer:
    global _query_analyzer
    if _query_analyzer is None:
        _query_analyzer = SpectrumQueryAnalyzer()
    return _query_analyzer


def _get_vector_retriever() -> VectorRetriever:
    global _vector_retriever
    if _vector_retriever is None:
        from ..vectorstores.chroma_store import ChromaStore
        from ..embeddings.sentence_transformer import SentenceTransformersEmbeddingProvider
        from pathlib import Path

        persist_dir = Path(__file__).resolve().parents[3] / "data" / "chroma"
        emb = SentenceTransformersEmbeddingProvider()
        store = ChromaStore(persist_dir=persist_dir, embedding_provider=emb)
        _vector_retriever = VectorRetriever(store)
    return _vector_retriever


def _get_keyword_retriever() -> KeywordRetriever | None:
    global _keyword_retriever
    if _keyword_retriever is None:
        kw = KeywordRetriever()
        if kw.is_available():
            _keyword_retriever = kw
    return _keyword_retriever


def _get_graph_retriever():
    global _graph_retriever
    if _graph_retriever is None:
        from ..retrievers.graph_retriever import GraphRetriever
        gr = GraphRetriever()
        if gr.is_available():
            _graph_retriever = gr
    return _graph_retriever


def _get_reranker() -> Reranker:
    global _reranker
    if _reranker is None:
        _reranker = Reranker()
    return _reranker


def _get_context_packer() -> ContextPacker:
    global _context_packer
    if _context_packer is None:
        _context_packer = ContextPacker()
    return _context_packer


def _get_answer_generator() -> AnswerGenerator:
    global _answer_generator
    if _answer_generator is None:
        _answer_generator = AnswerGenerator()
    return _answer_generator


# ── nodes ──

async def analyze_query_node(state: RAGState) -> dict[str, Any]:
    question = state.get("question", "")
    if not question:
        return {"error": "No question provided", "query_info": {}}

    analyzer = _get_analyzer()
    qi = analyzer.analyze(question)
    return {
        "query_info": qi.to_dict(),
        "debug": {"query_analysis": qi.to_dict()},
    }


async def retrieve_vector_node(state: RAGState) -> dict[str, Any]:
    retriever = _get_vector_retriever()
    question = state["question"]
    results = retriever.retrieve(question)
    return {
        "vector_results": results,
        "debug": {**state.get("debug", {}), "vector_count": len(results)},
    }


async def retrieve_keyword_node(state: RAGState) -> dict[str, Any]:
    kw = _get_keyword_retriever()
    if kw is None:
        return {
            "keyword_results": [],
            "debug": {**state.get("debug", {}), "keyword_count": 0},
        }

    question = state["question"]
    results = kw.retrieve(question)
    # normalize to same format as vector results
    normalized = []
    for r in results:
        normalized.append({
            "block_id": r.get("source", ""),
            "text": r.get("text", ""),
            "metadata": {
                "source_path": r.get("source", ""),
                "page_idx": 0,
                "block_type": "text",
            },
            "score": r.get("score", 0),
        })
    return {
        "keyword_results": normalized,
        "debug": {**state.get("debug", {}), "keyword_count": len(results)},
    }


async def retrieve_graph_node(state: RAGState) -> dict[str, Any]:
    gr = _get_graph_retriever()
    if gr is None:
        return {
            "graph_results": [],
            "debug": {**state.get("debug", {}), "graph_count": 0},
        }

    query_info = state.get("query_info", {})
    results = gr.retrieve(query_info)
    return {
        "graph_results": results,
        "debug": {**state.get("debug", {}), "graph_count": len(results)},
    }


async def rerank_results_node(state: RAGState) -> dict[str, Any]:
    reranker = _get_reranker()
    combined = state.get("vector_results", []) + state.get("keyword_results", [])
    query_info = state.get("query_info", {})

    # Convert query_info dict to QueryInfo for reranker
    from ..retrievers.query_analyzer import QueryInfo
    qi = QueryInfo(
        frequency_range=query_info.get("frequency_range"),
        region=query_info.get("region"),
        country=query_info.get("country"),
        radio_service=query_info.get("radio_service"),
        standard=query_info.get("standard"),
        footnote=query_info.get("footnote"),
        intent=query_info.get("intent", "general"),
        raw_query=state["question"],
    )

    graph_results = state.get("graph_results", [])
    reranked = reranker.rerank(combined, qi, graph_results=graph_results)
    return {
        "reranked_results": reranked,
        "debug": {**state.get("debug", {}), "reranked_count": len(reranked)},
    }


async def pack_context_node(state: RAGState) -> dict[str, Any]:
    packer = _get_context_packer()
    packed = packer.pack(state.get("reranked_results", []))
    return {
        "final_context": packed.context_text,
        "citations": packed.citations,
        "debug": {
            **state.get("debug", {}),
            "packed_blocks": packed.block_count,
            "total_retrieved": packed.total_retrieved,
        },
    }


async def generate_answer_node(state: RAGState) -> dict[str, Any]:
    generator = _get_answer_generator()
    answer, citations = await generator.generate(
        question=state["question"],
        context=state.get("final_context", ""),
        citations=state.get("citations", []),
    )
    return {
        "answer": answer,
        "citations": citations,
        "debug": {**state.get("debug", {}), "answer_length": len(answer)},
    }


async def analyze_retrieved_images_node(state: RAGState) -> dict[str, Any]:
    """Check retrieved results for multimodal blocks and run VLM/LLM analysis.

    Aligned with RAG-Anything's query-time multimodal analysis:
    - Images → VLM (Qwen-VL)
    - Tables → LLM analysis
    - Equations → LLM analysis
    """
    import os

    reranked = state.get("reranked_results", [])
    question = state.get("question", "")

    # Build LLM chat function for non-image modalities
    llm_chat = None
    try:
        from ...llm.client import chat
        from ...config import get_settings
        settings = get_settings()
        provider = settings.provider_profile()
        async def _chat(msgs):
            reply, _meta = await chat(msgs,
                provider_override=provider.provider, model_override=provider.model)
            return reply
        llm_chat = _chat
    except Exception:
        pass

    from ..multimodal.query_analyzer import enhance_retrieved_multimodal
    analyses = await enhance_retrieved_multimodal(reranked, question, llm_chat)

    final_context = state.get("final_context", "")
    for a in analyses:
        final_context += f"\n\n{a}"

    return {
        "final_context": final_context,
        "debug": {**state.get("debug", {}), "vlm_multimodal_analyzed": len(analyses)},
    }
