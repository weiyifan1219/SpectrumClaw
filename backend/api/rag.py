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
    """Upload a PDF, parse it, and return the content_list."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are supported")

    upload_dir = PROJECT_ROOT / "data" / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / file.filename

    content = await file.read()
    file_path.write_bytes(content)

    from ..rag.parsers.pypdf_parser import PyPDFParser
    from ..rag.processors.text import TextProcessor
    from ..rag.processors.table import TableProcessor

    parser = PyPDFParser()
    doc = parser.parse(str(file_path))

    text_proc = TextProcessor()
    table_proc = TableProcessor()
    for block in doc.blocks:
        if block.block_type in ("table",):
            table_proc.process(block)
        else:
            text_proc.process(block)

    # Save content_list.json
    out_dir = PARSED_DIR / doc.doc_id
    out_dir.mkdir(parents=True, exist_ok=True)
    content_list = [b.to_dict() for b in doc.blocks]
    (out_dir / "content_list.json").write_text(
        json.dumps(content_list, ensure_ascii=False, indent=2)
    )
    (out_dir / "raw_text.md").write_text(
        "\n\n".join(b.content for b in doc.blocks)
    )

    return {
        "doc_id": doc.doc_id,
        "filename": doc.filename,
        "block_count": len(doc.blocks),
        "parsed_at": doc.parsed_at,
        "content_list": content_list[:5],  # first 5 preview
    }


@router.post("/index")
async def handle_index(req: IndexRequest):
    """Index documents using the full DocumentProcessor pipeline."""
    import asyncio
    import os
    from ..rag.ingest import _build_doc_processor  # shared factory

    paths = req.file_paths
    if not paths:
        if UPLOADS_DIR.exists():
            paths = [str(p) for p in UPLOADS_DIR.glob("*.pdf")]

    if not paths:
        return {"indexed_files": 0, "total_blocks": 0, "error": "No files found"}

    processor = _build_doc_processor()
    results = []
    for fp in paths:
        try:
            r = asyncio.run(processor.process_document(str(fp)))
            results.append(r)
        except Exception as exc:
            results.append({"file": fp, "error": str(exc)})

    from ..rag.embeddings.sentence_transformer import SentenceTransformersEmbeddingProvider
    from ..rag.vectorstores.chroma_store import ChromaStore
    emb = SentenceTransformersEmbeddingProvider()
    store = ChromaStore(persist_dir=CHROMA_DIR, embedding_provider=emb)

    total_blocks = sum(r.text_blocks + r.multimodal_items for r in results if hasattr(r, 'text_blocks'))
    return {
        "indexed_files": len(paths),
        "total_blocks": total_blocks,
        "vector_count": store.count(),
        "entities_added": sum(r.entities_added for r in results if hasattr(r, 'entities_added')),
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


@router.get("/debug/{query_id}")
async def handle_debug(query_id: str):
    """Placeholder for query debug info."""
    return {"query_id": query_id, "debug": {}}
