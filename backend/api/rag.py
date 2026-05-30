"""RAG API endpoints — upload, index, query, debug."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel

router = APIRouter(prefix="/api/rag")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PARSED_DIR = PROJECT_ROOT / "data" / "parsed"


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
    """Index parsed documents into Chroma vector store."""
    from ..rag.parsers.pypdf_parser import PyPDFParser
    from ..rag.processors.text import TextProcessor
    from ..rag.processors.table import TableProcessor
    from ..rag.embeddings.sentence_transformer import SentenceTransformersEmbeddingProvider
    from ..rag.vectorstores.chroma_store import ChromaStore

    chroma_dir = PROJECT_ROOT / "data" / "chroma"
    emb = SentenceTransformersEmbeddingProvider()
    store = ChromaStore(persist_dir=chroma_dir, embedding_provider=emb)

    parser = PyPDFParser()
    text_proc = TextProcessor()
    table_proc = TableProcessor()

    # If specific files given, use those; otherwise use all in uploads
    paths = req.file_paths
    if not paths:
        upload_dir = PROJECT_ROOT / "data" / "uploads"
        if upload_dir.exists():
            paths = [str(p) for p in upload_dir.glob("*.pdf")]

    total_blocks = 0
    for fp in paths:
        doc = parser.parse(fp)
        for block in doc.blocks:
            if block.block_type in ("table",):
                table_proc.process(block)
            else:
                text_proc.process(block)
        store.add_blocks(doc.blocks)

        # Save parsed output
        out_dir = PARSED_DIR / doc.doc_id
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "content_list.json").write_text(
            json.dumps([b.to_dict() for b in doc.blocks], ensure_ascii=False, indent=2)
        )
        total_blocks += len(doc.blocks)

    return {
        "indexed_files": len(paths),
        "total_blocks": total_blocks,
        "vector_count": store.count(),
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


@router.get("/debug/{query_id}")
async def handle_debug(query_id: str):
    """Placeholder for query debug info."""
    return {"query_id": query_id, "debug": {}}
