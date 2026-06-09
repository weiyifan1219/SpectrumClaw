"""Streaming RAG pipeline — async generator that yields SSE events for each stage."""

from __future__ import annotations

import re
import time
from typing import Any, AsyncIterator

from .nodes import (
    _get_analyzer,
    _get_context_packer,
    _get_graph_retriever,
    _get_keyword_retriever,
    _get_reranker,
    _get_vector_retriever,
)
from ..chains.prompts import (
    SPECTRUM_FREQ_PLAN_SYSTEM_PROMPT,
    SPECTRUM_FREQ_PLAN_USER_TEMPLATE,
    SPECTRUM_RAG_SYSTEM_PROMPT,
    SPECTRUM_RAG_USER_TEMPLATE,
)
from ..retrievers.query_analyzer import QueryInfo


_FOOTNOTE_RE = re.compile(r"5\.\d{3}[A-Z]?")


async def stream_rag_query(
    question: str,
    profile: str = "default",
    thinking_enabled: bool = False,
) -> AsyncIterator[dict[str, Any]]:
    """Run the RAG pipeline and yield SSE events at each stage.

    profile="frequency_plan" swaps in the frequency-planning prompt and adds a
    bounded second retrieval pass (footnotes + adjacent bands). The generic
    "default" profile keeps the original single-pass behaviour byte-for-byte.
    """
    is_fp = profile == "frequency_plan"
    debug: dict[str, Any] = {}
    t_start = time.monotonic()
    query_info = None
    reranked: list[dict[str, Any]] = []
    citations: list[Any] = []
    counts = {"vector": 0, "keyword": 0, "graph": 0}
    answer_ok = False
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
        counts = {"vector": len(vec_results), "keyword": len(kw_results), "graph": len(graph_results)}

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

        # ── stage 3b: multi-hop (frequency_plan only) ──
        # Planning needs the primary band PLUS its footnotes and adjacent bands.
        # Scan pass-1 context for footnote refs + region hints, run one bounded
        # follow-up retrieval, and merge. Falls back to pass-1 on any failure.
        if is_fp and reranked:
            yield {"type": "stage", "stage": "multihop", "label": "Footnote/Adjacent Retrieval"}
            try:
                pass1_text = " ".join(d.get("text", "") for d in reranked)
                footnotes = list(dict.fromkeys(_FOOTNOTE_RE.findall(pass1_text)))[:4]
                hop_parts = []
                if footnotes:
                    hop_parts.append("脚注 " + " ".join(footnotes))
                if query_info and getattr(query_info, "region", ""):
                    hop_parts.append(query_info.region)
                hop_parts.append(f"{question} 相邻频段 共存 保护 协调 限制")
                hop_query = " ".join(hop_parts)

                hop_docs: list[dict[str, Any]] = []
                try:
                    r = _get_vector_retriever()
                    for d in r.retrieve(hop_query, where=None):
                        hop_docs.append({"text": d.get("text", ""), "metadata": d.get("metadata", {}),
                                         "score": d.get("score", d.get("metadata", {}).get("score", 0)),
                                         "block_id": d.get("block_id", "")})
                except Exception:
                    pass
                try:
                    r = _get_keyword_retriever()
                    if r:
                        for d in r.retrieve(hop_query):
                            hop_docs.append({"text": d.get("text", ""), "metadata": d.get("metadata", {}),
                                             "score": d.get("score", d.get("metadata", {}).get("score", 0)),
                                             "block_id": d.get("block_id", "")})
                except Exception:
                    pass

                # dedup hop docs against pass-1 using the same key, then rerank+merge
                existing_keys = {
                    d.get("metadata", {}).get("source_path", "") + str(d.get("metadata", {}).get("page_idx", "")) + d.get("text", "")[:100]
                    for d in reranked
                }
                new_docs = []
                seen = set(existing_keys)
                for d in hop_docs:
                    key = d.get("metadata", {}).get("source_path", "") + str(d.get("metadata", {}).get("page_idx", "")) + d.get("text", "")[:100]
                    if key not in seen:
                        seen.add(key)
                        new_docs.append(d)
                if new_docs:
                    try:
                        reranker = _get_reranker()
                        new_ranked = reranker.rerank(new_docs, query_info, top_k=6)
                    except Exception:
                        new_ranked = new_docs[:6]
                    reranked = (reranked + new_ranked)[:12]
                yield {"type": "stage_done", "stage": "multihop",
                       "counts": {"footnotes": len(footnotes), "added": len(new_docs)}}
            except Exception:
                yield {"type": "stage_done", "stage": "multihop", "counts": {"footnotes": 0, "added": 0}}

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

                if is_fp:
                    sys_prompt = SPECTRUM_FREQ_PLAN_SYSTEM_PROMPT
                    user_tmpl = SPECTRUM_FREQ_PLAN_USER_TEMPLATE
                else:
                    sys_prompt = SPECTRUM_RAG_SYSTEM_PROMPT
                    user_tmpl = SPECTRUM_RAG_USER_TEMPLATE

                messages = [
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user_tmpl.format(
                        context=context, question=question)},
                ]

                async for event in stream_chat(
                    messages,
                    provider_override=provider.provider,
                    model_override=provider.model,
                    thinking_enabled=thinking_enabled,
                    reasoning_effort="high" if thinking_enabled else None,
                ):
                    etype = event.get("type")
                    if etype == "content":
                        yield {"type": "content", "data": event["data"]}
                    elif etype == "thinking":
                        yield {"type": "thinking", "data": event["data"]}
                answer_ok = True

            except Exception as exc:
                yield {"type": "content", "data": f"\n\n(回答生成失败: {exc})"}

        yield {"type": "stage_done", "stage": "answer"}

        # ── memory write (best-effort, never blocks response) ──
        _record_rag_memory(
            question=question,
            query_info=query_info,
            reranked=reranked,
            citations=citations,
            counts=counts,
            latency_ms=int((time.monotonic() - t_start) * 1000),
            status="success" if answer_ok else "empty",
        )

        # ── done ──
        yield {"type": "done", "citations": citations, "debug": debug}

    except Exception as exc:
        _record_rag_memory(
            question=question,
            query_info=query_info,
            reranked=reranked,
            citations=citations,
            counts=counts,
            latency_ms=int((time.monotonic() - t_start) * 1000),
            status="failed",
            error=str(exc),
        )
        yield {"type": "error", "data": str(exc)}


def _record_rag_memory(
    question: str,
    query_info: Any,
    reranked: list[dict[str, Any]],
    citations: list[Any],
    counts: dict[str, int],
    latency_ms: int,
    status: str,
    error: str = "",
) -> None:
    """Persist a RAG query as an episodic memory + a skill_run. Best-effort."""
    try:
        from ...config import get_settings

        settings = get_settings()
        if not settings.memory_enabled:
            return
        from ...memory.service import MemoryService

        mem = MemoryService(db_path=settings.memory_db_path)

        n_blocks = len(reranked)
        top_source = ""
        if reranked:
            meta = reranked[0].get("metadata", {}) or {}
            top_source = meta.get("source") or meta.get("source_path") or meta.get("doc_id") or ""
        service_tag = ""
        if query_info is not None:
            service_tag = getattr(query_info, "radio_service", "") or getattr(query_info, "intent", "") or ""

        # episodic memory of the query
        q_short = question[:120]
        mem.add_memory(
            text=f"RAG查询: {q_short} → 命中{n_blocks}块" + (f", 主来源 {top_source}" if top_source else ""),
            kind="episodic",
            tags=[t for t in ["rag", service_tag] if t],
            confidence=0.7 if status == "success" else 0.3,
        )

        # skill_run for audit + stats
        rag_refs = []
        for c in (citations or [])[:5]:
            if isinstance(c, dict):
                rag_refs.append(str(c.get("source") or c.get("source_path") or c.get("id") or ""))
            else:
                rag_refs.append(str(c))
        mem.record_skill_run(
            skill_name="rag_query",
            input_data={"question": q_short},
            output_summary=(
                f"命中{n_blocks}块, vec/kw/graph="
                f"{counts.get('vector', 0)}/{counts.get('keyword', 0)}/{counts.get('graph', 0)}"
                + (f", 主来源 {top_source}" if top_source else "")
            )[:200],
            status="success" if status == "success" else "failed",
            latency_ms=latency_ms,
            error=error[:200],
            rag_refs=[r for r in rag_refs if r],
        )
    except Exception:
        pass
