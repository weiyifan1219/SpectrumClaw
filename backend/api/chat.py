from __future__ import annotations

import json as _json
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..config import get_settings
from ..agent.run_events import error as run_error
from ..agent.run_events import standardize_event
from ..llm.client import chat as llm_chat
from ..llm.model_registry import llm_options_payload
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
    thread_id: str = ""


class ChatResponse(BaseModel):
    reply: str
    metadata: dict[str, Any]


@router.get("/api/llm/options")
async def handle_llm_options() -> dict[str, Any]:
    return llm_options_payload(get_settings())


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
                thread_id=request.thread_id,
            ):
                event = standardize_event(event, source="chat")
                yield f"data: {_json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as exc:
            yield f"data: {_json.dumps(run_error(str(exc), source='chat'), ensure_ascii=False)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/api/kb/stats")
async def handle_kb_stats():
    """Return real knowledge base statistics including RAG pipeline status."""
    try:
        from ..knowledge.retrieve import get_meta, is_ready
    except ImportError:
        from backend.knowledge.retrieve import get_meta, is_ready

    stats = get_meta()

    # Add RAG pipeline status
    try:
        from ..rag.paths import CHROMA_DIR, GRAPH_PATH
        chroma_dir = CHROMA_DIR
        graph_path = GRAPH_PATH

        if (chroma_dir / "chroma.sqlite3").exists():
            # Fast count via sqlite — avoid loading embedding model (5-15s) on every call
            import sqlite3
            try:
                db = sqlite3.connect(str(chroma_dir / "chroma.sqlite3"))
                vec_count = db.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
                db.close()
            except Exception:
                vec_count = 0
            stats["rag_pipeline"] = {
                "status": "ready",
                "vector_count": vec_count,
                "backend": "ChromaDB + sentence-transformers",
            }
        else:
            stats["rag_pipeline"] = {"status": "not indexed"}

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

        # Prefer the live RAG doc registry for document count (TF-IDF meta is stale).
        try:
            from ..rag.doc_registry import list_docs
        except ImportError:
            from backend.rag.doc_registry import list_docs
        try:
            reg = list_docs()
            indexed = sum(1 for d in reg if d.get("status") == "indexed")
            if reg:
                stats["total_pdfs"] = indexed or len(reg)
        except Exception:
            pass

        # Fallback: count actual PDFs in raw directory if registry is empty/missing
        if not stats.get("total_pdfs"):
            from ..rag.paths import KB_RAW_DIR
            if KB_RAW_DIR.exists():
                stats["total_pdfs"] = sum(1 for _ in KB_RAW_DIR.glob("*.pdf"))
    except Exception as exc:
        stats["rag_pipeline"] = {"status": "error", "error": str(exc)}

    return stats
