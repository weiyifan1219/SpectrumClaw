"""RAG API endpoints — upload, index, query, debug."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel

from ..rag.paths import PROJECT_ROOT, PARSED_DIR, CHROMA_DIR, GRAPH_PATH, UPLOADS_DIR

router = APIRouter(prefix="/api/rag")


class QueryRequest(BaseModel):
    question: str


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


@router.get("/docs")
async def handle_docs():
    """List all parsed documents."""
    if not PARSED_DIR.exists():
        return {"docs": []}

    docs = []
    for d in sorted(PARSED_DIR.iterdir()):
        if d.is_dir():
            cl_path = d / "content_list.json"
            if cl_path.exists():
                data = json.loads(cl_path.read_text())
                docs.append({
                    "doc_id": d.name,
                    "block_count": len(data),
                    "has_content_list": True,
                })
    return {"docs": docs}


@router.get("/graph/entities")
async def handle_graph_entities(
    type: str | None = None,
    search: str | None = None,
    limit: int = 200,
):
    """Get knowledge graph entities, optionally filtered by type or search."""
    graph_path = GRAPH_PATH
    if not graph_path.exists():
        return {"entities": [], "relations": []}

    g = json.loads(graph_path.read_text())
    entities = g.get("entities", [])
    relations = g.get("relations", [])

    if type:
        entities = [e for e in entities if e.get("type") == type]
    if search:
        q = search.lower()
        entities = [e for e in entities if q in e.get("name", "").lower()]

    # Get relations involving filtered entities
    entity_names = {e["name"] for e in entities}
    filtered_relations = [
        r for r in relations
        if r.get("source") in entity_names or r.get("target") in entity_names
    ]

    return {
        "entities": entities[:limit],
        "relations": filtered_relations[:limit * 3],
        "total_entities": g.get("entity_count", 0),
        "total_relations": g.get("relation_count", 0),
    }


@router.get("/graph/entity/{name:path}")
async def handle_graph_entity(name: str):
    """Get a specific entity and all its relations."""
    graph_path = GRAPH_PATH
    if not graph_path.exists():
        return {"entity": None, "relations": []}

    g = json.loads(graph_path.read_text())
    entity = None
    for e in g.get("entities", []):
        if e.get("name") == name:
            entity = e
            break

    related = [
        r for r in g.get("relations", [])
        if r.get("source") == name or r.get("target") == name
    ]

    # Resolve related entity types
    entity_map = {e["name"]: e for e in g.get("entities", [])}
    for r in related:
        r["source_type"] = entity_map.get(r["source"], {}).get("type", "")
        r["target_type"] = entity_map.get(r["target"], {}).get("type", "")

    return {"entity": entity, "relations": related}


@router.get("/status")
async def handle_rag_status():
    """Return RAG indexing status — doc registry, index health, events."""
    from ..rag.doc_registry import list_docs, doc_count
    from ..rag.paths import CHROMA_DIR, GRAPH_PATH

    docs = list_docs()
    indexed = [d for d in docs if d.get("status") == "indexed"]
    failed = [d for d in docs if d.get("status") == "failed"]
    indexing = [d for d in docs if d.get("status") == "indexing"]

    # Chroma health
    chroma_ok = (CHROMA_DIR / "chroma.sqlite3").exists()
    graph_ok = GRAPH_PATH.exists()

    return {
        "registry": {
            "total": len(docs),
            "indexed": len(indexed),
            "failed": len(failed),
            "indexing": len(indexing),
        },
        "health": {
            "chroma": chroma_ok,
            "graph": graph_ok,
        },
        "recent_failures": [
            {"file": d.get("filename", ""), "error": d.get("error", "")}
            for d in failed[-10:]
        ],
    }


@router.get("/debug/{query_id}")
async def handle_debug(query_id: str):
    """Placeholder for query debug info."""
    return {"query_id": query_id, "debug": {}}
