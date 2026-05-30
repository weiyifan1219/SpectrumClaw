from __future__ import annotations

import json as _json
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..llm.client import chat as llm_chat
from ..agent.runtime import stream_chat as runtime_stream_chat

router = APIRouter()


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(default_factory=list)
    provider: str | None = None
    model: str | None = None
    thinking_enabled: bool = False
    reasoning_effort: str | None = None
    tool_names: list[str] | None = None


class ChatResponse(BaseModel):
    reply: str
    metadata: dict[str, Any]


@router.post("/api/chat", response_model=ChatResponse)
async def handle_chat(request: ChatRequest) -> ChatResponse:
    try:
        reply, metadata = await llm_chat(
            [m.model_dump() for m in request.messages],
            provider_override=request.provider,
            model_override=request.model,
            thinking_enabled=request.thinking_enabled,
            reasoning_effort=request.reasoning_effort,
            tool_names=request.tool_names,
        )
    except httpx.HTTPStatusError as exc:
        body = exc.response.text[:500].replace("\n", " ").strip()
        detail = f"LLM API returned {exc.response.status_code}"
        if body:
            detail = f"{detail}: {body}"
        raise HTTPException(status_code=502, detail=detail) from exc
    except httpx.HTTPError as exc:
        detail = f"LLM API request failed: {exc.__class__.__name__}"
        message = str(exc).strip()
        if message:
            detail = f"{detail}: {message[:500]}"
        raise HTTPException(status_code=502, detail=detail) from exc
    except ValueError as exc:
        status_code = 400 if str(exc).startswith("Unsupported LLM provider") else 502
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    return ChatResponse(reply=reply, metadata=metadata)


@router.post("/api/chat/stream")
async def handle_chat_stream(request: ChatRequest):
    async def generate():
        try:
            async for event in runtime_stream_chat(
                [m.model_dump() for m in request.messages],
                provider_override=request.provider,
                model_override=request.model,
                thinking_enabled=request.thinking_enabled,
                reasoning_effort=request.reasoning_effort,
                tool_names=request.tool_names,
            ):
                yield f"data: {_json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as exc:
            yield f"data: {_json.dumps({'type': 'error', 'data': str(exc)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/api/kb/stats")
async def handle_kb_stats():
    """Return real knowledge base statistics including RAG-Anything status."""
    try:
        from ..knowledge.retrieve import get_meta, is_ready
    except ImportError:
        from backend.knowledge.retrieve import get_meta, is_ready

    stats = get_meta()

    # Add RAG-Anything pipeline status
    try:
        from pathlib import Path
        chroma_dir = Path(__file__).resolve().parents[2] / "data" / "chroma"
        graph_path = Path(__file__).resolve().parents[2] / "data" / "graph" / "spectrum_graph.json"

        if (chroma_dir / "chroma.sqlite3").exists():
            from ..rag.embeddings.sentence_transformer import SentenceTransformersEmbeddingProvider
            from ..rag.vectorstores.chroma_store import ChromaStore
            emb = SentenceTransformersEmbeddingProvider()
            store = ChromaStore(persist_dir=chroma_dir, embedding_provider=emb)
            stats["rag_anything"] = {
                "status": "ready",
                "vector_count": store.count(),
                "backend": "ChromaDB + sentence-transformers",
            }
        else:
            stats["rag_anything"] = {"status": "not indexed"}

        if graph_path.exists():
            import json
            g = json.loads(graph_path.read_text())
            entities = g.get("entities", [])
            relations = g.get("relations", [])

            # entity type breakdown
            from collections import Counter
            etype_counts = Counter(e.get("type", "Unknown") for e in entities)
            entity_breakdown = [
                {"type": t, "count": c}
                for t, c in etype_counts.most_common()
            ]
            rtype_counts = Counter(r.get("relation", "Unknown") for r in relations)
            relation_breakdown = [
                {"type": t, "count": c}
                for t, c in rtype_counts.most_common()
            ]

            stats["knowledge_graph"] = {
                "status": "ready",
                "entity_count": g.get("entity_count", 0),
                "relation_count": g.get("relation_count", 0),
                "entity_breakdown": entity_breakdown,
                "relation_breakdown": relation_breakdown,
            }
        else:
            stats["knowledge_graph"] = {"status": "not built"}
    except Exception as exc:
        stats["rag_anything"] = {"status": "error", "error": str(exc)}

    return stats
