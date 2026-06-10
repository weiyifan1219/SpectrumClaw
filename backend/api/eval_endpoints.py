"""Evaluation-specific endpoints — isolated methods for RAG ablation study.

These endpoints exist solely for the eval pipeline and bypass the LangGraph
agent, providing clean baselines for comparison.
"""

from __future__ import annotations

import json

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/eval")


class EvalRequest(BaseModel):
    question: str
    top_k: int = Field(default=10, ge=1, le=50)


@router.post("/llm_only")
async def handle_llm_only(req: EvalRequest):
    """Direct LLM call — no retrieval context, no tools."""
    from ..llm.client import chat
    from ..config import get_settings

    settings = get_settings()
    provider = settings.provider_profile()

    messages = [{"role": "user", "content": req.question}]
    reply, meta = await chat(
        messages,
        provider_override=provider.provider,
        model_override=provider.model,
    )
    return {
        "answer": reply,
        "citations": [],
        "retrieved_blocks": [],
        "token_usage": meta.get("usage", {}),
    }


@router.post("/vector_rag")
async def handle_vector_rag(req: EvalRequest):
    """Vector-only retrieval + LLM generation. No keyword/graph/rerank."""
    from ..llm.client import chat
    from ..config import get_settings
    from ..rag.graph.nodes import _get_vector_retriever

    settings = get_settings()
    provider = settings.provider_profile()

    retriever = _get_vector_retriever()
    retriever.top_k = req.top_k
    blocks = retriever.retrieve(req.question)

    context_parts = []
    retrieved = []
    for i, b in enumerate(blocks):
        text = b.get("text", b.get("content", ""))
        meta = b.get("metadata", {})
        snippet = text[:500]
        context_parts.append(snippet)
        retrieved.append({
            "rank": i + 1,
            "block_id": b.get("block_id", b.get("id", "")),
            "doc_id": meta.get("doc_id", ""),
            "source_path": meta.get("source_path", meta.get("source", "")),
            "page_idx": meta.get("page_idx", meta.get("page", 0)),
            "block_type": meta.get("block_type", "text"),
            "score": round(float(b.get("score", b.get("relevance", 0))), 4),
            "rerank_score": None,
            "content_snippet": text[:200],
        })

    context = "\n\n---\n\n".join(context_parts)
    prompt = f"""Based on the following retrieved context, answer the user's question.
If the context doesn't contain sufficient information, say "信息不足".
Cite the source documents when possible.

Context:
{context}

Question: {req.question}

Answer in Chinese:"""

    messages = [{"role": "user", "content": prompt}]
    reply, meta = await chat(
        messages,
        provider_override=provider.provider,
        model_override=provider.model,
    )

    citations = [
        {"doc_id": b["doc_id"], "source_path": b["source_path"], "page_idx": b["page_idx"], "block_id": b["block_id"]}
        for b in retrieved[:5]
    ]

    return {
        "answer": reply,
        "citations": citations,
        "retrieved_blocks": retrieved,
        "token_usage": meta.get("usage", {}),
    }
