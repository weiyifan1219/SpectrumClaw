"""RAG API endpoints — upload, index, query, debug."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel

from ..rag.paths import PROJECT_ROOT, PARSED_DIR, CHROMA_DIR, GRAPH_PATH, UPLOADS_DIR
from ..runtime.jobs import get_job_store
from ..runtime.resident_state import get_resident_state

router = APIRouter(prefix="/api/rag")


class QueryRequest(BaseModel):
    question: str


class FreqPlanRequest(BaseModel):
    question: str
    thinking_enabled: bool = True


class QueryResponse(BaseModel):
    answer: str
    citations: list[dict[str, Any]]
    retrieved_blocks: list[dict[str, Any]]
    debug: dict[str, Any]


class IndexRequest(BaseModel):
    file_paths: list[str] = []


@router.post("/upload")
async def handle_upload(file: UploadFile = File(...)):
    """Upload a PDF and run the full parse+process pipeline."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are supported")

    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    file_path = UPLOADS_DIR / file.filename
    content = await file.read()
    file_path.write_bytes(content)

    from ..rag.ingest import _build_doc_processor
    processor = _build_doc_processor()
    result = await processor.process_document(str(file_path))
    get_resident_state().mark_rag_dirty()

    if result.errors:
        return {
            "doc_id": result.doc_id,
            "filename": file.filename,
            "block_count": result.text_blocks + result.multimodal_items,
            "entities_added": result.entities_added,
            "errors": result.errors,
        }

    # Read back parsed output for preview
    preview = []
    from ..rag.schemas.document import SpectrumDocument
    doc = SpectrumDocument.load(PARSED_DIR, result.doc_id)
    if doc:
        preview = [b.to_dict() for b in doc.blocks[:5]]

    return {
        "doc_id": result.doc_id,
        "filename": file.filename,
        "block_count": result.text_blocks + result.multimodal_items,
        "entities_added": result.entities_added,
        "relations_added": result.relations_added,
        "content_list": preview,
    }


@router.post("/index")
async def handle_index(req: IndexRequest):
    """Index documents using the full DocumentProcessor pipeline."""
    from ..rag.ingest import index_documents

    paths = req.file_paths
    if not paths:
        if UPLOADS_DIR.exists():
            paths = [str(p) for p in UPLOADS_DIR.glob("*.pdf")]

    if not paths:
        return {"indexed_files": 0, "total_blocks": 0, "error": "No files found"}

    result = await index_documents(paths, clear=False, use_cache=True)
    get_resident_state().mark_rag_dirty()
    return {
        "indexed_files": result.get("total_pdfs", 0),
        "total_attempted": result.get("total_attempted", len(paths)),
        "total_blocks": result.get("total_blocks", 0),
        "vector_count": result.get("vector_count", 0),
        "entities_added": result.get("graph_entities", 0),
        "failed": result.get("errors", []),
    }


@router.post("/query", response_model=QueryResponse)
async def handle_query(req: QueryRequest):
    """Run the full RAG pipeline and return answer with citations."""
    from ..rag.graph.workflow import run_rag_query

    result = await run_rag_query(req.question)

    if result.get("error"):
        raise HTTPException(500, result["error"])

    return QueryResponse(
        answer=result["answer"],
        citations=result["citations"],
        retrieved_blocks=result.get("debug", {}).get("retrieved_blocks", []),
        debug=result.get("debug", {}),
    )


@router.post("/stream")
async def handle_rag_stream(req: QueryRequest):
    """Run the RAG pipeline with SSE streaming — stage events + answer tokens."""
    from ..agent.run_events import error as run_error
    from ..agent.run_events import standardize_event
    from ..rag.graph.stream import stream_rag_query
    job_id = get_job_store().start_job(
        kind="rag",
        title=f"RAG · {req.question[:48] or 'stream'}",
        prompt_preview=req.question[:160],
    )

    async def generate():
        try:
            async for event in stream_rag_query(req.question):
                event = standardize_event(event, source="rag")
                event = get_job_store().record_event(job_id, event)
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as exc:
            event = get_job_store().record_event(job_id, run_error(str(exc), source="rag"))
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/frequency_plan/stream")
async def handle_freq_plan_stream(req: FreqPlanRequest):
    """Frequency-planning RAG stream — FP-specific prompt + multi-hop retrieval
    + thinking events + a trailing structured JSON block in the answer."""
    from ..agent.run_events import error as run_error
    from ..agent.run_events import standardize_event
    from ..rag.graph.stream import stream_rag_query
    job_id = get_job_store().start_job(
        kind="frequency_plan",
        title=f"Frequency Plan · {req.question[:48] or 'stream'}",
        prompt_preview=req.question[:160],
    )

    async def generate():
        try:
            async for event in stream_rag_query(
                req.question, profile="frequency_plan", thinking_enabled=req.thinking_enabled
            ):
                event = standardize_event(event, source="frequency_plan")
                event = get_job_store().record_event(job_id, event)
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as exc:
            event = get_job_store().record_event(job_id, run_error(str(exc), source="frequency_plan"))
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/docs")
async def handle_docs(
    status: str | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    """List indexed documents from the doc registry (paginated)."""
    docs = get_resident_state().list_docs(status=status)
    if search:
        q = search.lower()
        docs = [d for d in docs if q in d.get("filename", "").lower()]

    # newest-indexed first when timestamps exist, else stable order
    docs.sort(key=lambda d: d.get("indexed_at", "") or d.get("registered_at", ""), reverse=True)

    total = len(docs)
    page = docs[offset:offset + limit]
    items = [
        {
            "doc_id": d.get("content_hash", ""),
            "filename": d.get("filename", ""),
            "status": d.get("status", ""),
            "parser": d.get("parser_name", ""),
            "error": d.get("error", ""),
        }
        for d in page
    ]

    # status tallies across the (search-filtered) set
    counts: dict[str, int] = {}
    for d in docs:
        s = d.get("status", "unknown")
        counts[s] = counts.get(s, 0) + 1

    return {"docs": items, "total": total, "offset": offset, "limit": limit, "status_counts": counts}


@router.get("/docs/{doc_id}/pdf")
async def handle_doc_pdf(doc_id: str, filename: str | None = None):
    """Stream the original PDF for inline preview. Resolves the file by registry
    content_hash first, then falls back to matching by filename (citations carry
    a source path, not the registry hash). Only serves registered files."""
    import os
    docs = get_resident_state().list_docs()
    match = next((d for d in docs if d.get("content_hash") == doc_id), None)

    # fallback: match by filename (basename), used by query-page citations
    if not match and filename:
        base = os.path.basename(filename)
        match = next((d for d in docs if d.get("filename") == base), None)
        if not match:
            stem = base.rsplit(".", 1)[0]
            match = next((d for d in docs if (d.get("filename") or "").startswith(stem)), None)

    if not match:
        raise HTTPException(status_code=404, detail="document not found")

    path = match.get("file_path", "")
    if not path or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="PDF file missing on server")

    fname = match.get("filename") or os.path.basename(path)
    return FileResponse(
        path,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{fname}"'},
    )


@router.get("/graph/entities")
async def handle_graph_entities(
    type: str | None = None,
    search: str | None = None,
    limit: int = 200,
):
    """Get knowledge graph entities, optionally filtered by type or search."""
    return get_resident_state().graph_entities(entity_type=type, search=search, limit=limit)


@router.get("/graph/entity/{name:path}")
async def handle_graph_entity(name: str):
    """Get a specific entity and all its relations."""
    return get_resident_state().graph_entity(name)


@router.get("/status")
async def handle_rag_status():
    """Return RAG indexing status — doc registry, index health, ingest events."""
    return get_resident_state().rag_status()


@router.get("/debug/{query_id}")
async def handle_debug(query_id: str):
    """Placeholder for query debug info."""
    return {"query_id": query_id, "debug": {}}
