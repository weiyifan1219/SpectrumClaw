"""Streaming RAG pipeline — async generator that yields SSE events for each stage."""

from __future__ import annotations

from typing import Any, AsyncIterator

from .nodes import (
    _get_analyzer,
    _get_context_packer,
    _get_graph_retriever,
    _get_keyword_retriever,
    _get_reranker,
    _get_vector_retriever,
)
from ..chains.prompts import SPECTRUM_RAG_SYSTEM_PROMPT, SPECTRUM_RAG_USER_TEMPLATE
from ..retrievers.query_analyzer import QueryInfo


async def stream_rag_query(question: str) -> AsyncIterator[dict[str, Any]]:
    """Run the RAG pipeline and yield SSE events at each stage."""
    debug: dict[str, Any] = {}
    try:
        # ── stage 1: query analysis ──
        yield {"type": "stage", "stage": "query_analysis", "label": "Query Analysis"}
        analyzer = _get_analyzer()
        query_info: QueryInfo = analyzer.analyze(question)
        debug["query_analysis"] = {
            "frequency_range": query_info.frequency_range or "",
            "region": query_info.region or "",
            "radio_service": query_info.radio_service or "",
            "intent": query_info.intent or "",
        }
        yield {"type": "stage_done", "stage": "query_analysis"}

        # ── stage 2: retrieval (vector + keyword + graph) ──
        yield {"type": "stage", "stage": "retrieval", "label": "Hybrid Retrieval"}

        vec_results: list[dict[str, Any]] = []
        kw_results: list[dict[str, Any]] = []
        graph_results: list[dict[str, Any]] = []

        try:
            r = _get_vector_retriever()
            docs = r.retrieve(question, where=None)
            vec_results = [{"text": d.get("text", ""), "metadata": d.get("metadata", {}),
                            "score": d.get("score", d.get("metadata", {}).get("score", 0)),
                            "block_id": d.get("block_id", "")} for d in docs]
        except Exception:
            pass

        try:
            r = _get_keyword_retriever()
            if r:
                docs = r.retrieve(question)
                kw_results = [{"text": d.get("text", ""), "metadata": d.get("metadata", {}),
                               "score": d.get("score", d.get("metadata", {}).get("score", 0)),
                               "block_id": d.get("block_id", "")} for d in docs]
        except Exception:
            pass

        try:
            r = _get_graph_retriever()
            if r:
                graph_results = r.retrieve(query_info)
        except Exception:
            pass
        yield {"type": "stage_done", "stage": "retrieval",
               "counts": {"vector": len(vec_results), "keyword": len(kw_results), "graph": len(graph_results)}}

        # ── stage 3: rerank ──
        yield {"type": "stage", "stage": "rerank", "label": "Rerank"}
        all_docs = vec_results + kw_results
        reranked: list[dict[str, Any]] = []
        if all_docs:
            deduped: dict[str, dict[str, Any]] = {}
            for d in all_docs:
                key = d.get("metadata", {}).get("source_path", "") + str(d.get("metadata", {}).get("page_idx", "")) + d.get("text", "")[:100]
                if key not in deduped:
                    deduped[key] = d
            unique_docs = list(deduped.values())
            try:
                reranker = _get_reranker()
                reranked = reranker.rerank(unique_docs, query_info, graph_results=graph_results or None, top_k=10)
            except Exception:
                reranked = unique_docs[:10]
        yield {"type": "stage_done", "stage": "rerank", "count": len(reranked)}

        # ── stage 4: pack context ──
        packer = _get_context_packer()
        packed = packer.pack(reranked)
        context = packed.context_text
        citations = packed.citations
        debug["retrieved_blocks"] = [
            {"text": d.get("text", "")[:300], "metadata": d.get("metadata", {}),
             "score": d.get("rerank_score", d.get("score", 0))}
            for d in reranked[:15]
        ]

        # ── stage 5: answer generation (streaming) ──
        yield {"type": "stage", "stage": "answer", "label": "Answer Generation"}

        if not context:
            answer = (
                "根据当前检索结果，未能找到与您问题相关的频谱文档。"
                "建议：\n1. 尝试使用不同的关键词重新提问\n2. 确认知识库中已索引相关ITU-R文档"
            )
            yield {"type": "content", "data": answer}
        else:
            try:
                from ...llm.client import stream_chat
                from ...config import get_settings

                settings = get_settings()
                provider = settings.provider_profile()

                messages = [
                    {"role": "system", "content": SPECTRUM_RAG_SYSTEM_PROMPT},
                    {"role": "user", "content": SPECTRUM_RAG_USER_TEMPLATE.format(
                        context=context, question=question)},
                ]

                async for event in stream_chat(
                    messages,
                    provider_override=provider.provider,
                    model_override=provider.model,
                ):
                    if event.get("type") == "content":
                        yield {"type": "content", "data": event["data"]}

            except Exception as exc:
                yield {"type": "content", "data": f"\n\n(回答生成失败: {exc})"}

        yield {"type": "stage_done", "stage": "answer"}

        # ── done ──
        yield {"type": "done", "citations": citations, "debug": debug}

    except Exception as exc:
        yield {"type": "error", "data": str(exc)}
