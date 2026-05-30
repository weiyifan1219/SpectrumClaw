"""RAG CLI — unified command-line interface for indexing, evaluation, and inspection.

Usage:
    python -m backend.rag.cli index [--incremental] [--path DATA_DIR]
    python -m backend.rag.cli reindex --doc-id XXX
    python -m backend.rag.cli eval [--output REPORT_DIR]
    python -m backend.rag.cli inspect --doc-id XXX
    python -m backend.rag.cli status
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from datetime import datetime, timezone

PROJECT_ROOT = Path(__file__).resolve().parents[3]
REGISTRY_PATH = PROJECT_ROOT / "data" / "index" / "doc_registry.json"


# ── helpers ──

def _load_registry() -> dict:
    if REGISTRY_PATH.exists():
        return json.loads(REGISTRY_PATH.read_text())
    return {"docs": {}, "index_version": "v1", "embedding_model": "", "embedding_dim": 0}


def _save_registry(reg: dict):
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(json.dumps(reg, ensure_ascii=False, indent=2))


# ── commands ──

def _status():
    reg = _load_registry()
    print(f"Doc registry: {len(reg.get('docs', {}))} documents")
    print(f"Index version: {reg.get('index_version', '?')}")
    print(f"Embedding: {reg.get('embedding_model', '?')} ({reg.get('embedding_dim', '?')} dim)")
    # Chroma
    chroma = PROJECT_ROOT / "data" / "chroma" / "chroma.sqlite3"
    print(f"ChromaDB: {'present' if chroma.exists() else 'missing'} "
          f"({os.path.getsize(chroma) / 1024 / 1024:.1f} MB)" if chroma.exists() else "ChromaDB: missing")
    # Graph
    graph = PROJECT_ROOT / "data" / "graph" / "spectrum_graph.json"
    if graph.exists():
        g = json.loads(graph.read_text())
        print(f"Graph: {g.get('entity_count', 0)} entities, {g.get('relation_count', 0)} relations")


def _index(path: str | None = None, incremental: bool = False):
    """Index PDFs, optionally incremental."""
    from ..ingest import ingest
    from ..schemas.document import SpectrumDocument

    pdf_dir = Path(path) if path else (PROJECT_ROOT / "data" / "knowledge_base" / "raw")
    if not pdf_dir.exists():
        print(f"Directory not found: {pdf_dir}", file=sys.stderr)
        sys.exit(1)

    pdfs = sorted(str(p) for p in pdf_dir.glob("*.pdf"))
    if incremental:
        reg = _load_registry()
        existing = set(reg.get("docs", {}).keys())
        pdfs = [p for p in pdfs
                if SpectrumDocument.make_doc_id(p) not in existing]
        print(f"Incremental: {len(pdfs)} new PDFs (skipping {len(existing)} existing)")

    result = ingest(pdf_paths=pdfs)
    if result.get("errors"):
        print(f"Errors: {len(result['errors'])} files skipped")

    # Update registry
    reg = _load_registry()
    reg["index_version"] = "v1"
    from ..parsers.pypdf_parser import PyPDFParser
    parser = PyPDFParser()
    for fp in pdfs:
        doc_id = SpectrumDocument.make_doc_id(fp)
        reg["docs"][doc_id] = {
            "filename": os.path.basename(fp),
            "source_path": fp,
            "parser": parser.name,
            "parser_version": parser.version,
            "indexed_at": datetime.now(timezone.utc).isoformat(),
        }
    _save_registry(reg)
    print(f"Registry updated: {len(reg['docs'])} total documents")


def _reindex(doc_id: str):
    reg = _load_registry()
    info = reg["docs"].get(doc_id)
    if not info:
        print(f"Document {doc_id} not in registry", file=sys.stderr)
        sys.exit(1)

    fp = info.get("source_path", "")
    if not os.path.exists(fp):
        print(f"Source file not found: {fp}", file=sys.stderr)
        sys.exit(1)

    from ..ingest import ingest
    ingest(pdf_paths=[fp], clear=False)
    info["indexed_at"] = datetime.now(timezone.utc).isoformat()
    reg["docs"][doc_id] = info
    _save_registry(reg)
    print(f"Reindexed: {doc_id} ({info['filename']})")


def _eval_cmd(output: str | None = None):
    import asyncio, json
    from ..evaluation.run_eval import run_eval
    report = asyncio.run(run_eval())
    out_dir = Path(output) if output else (PROJECT_ROOT / "data" / "eval" / "reports")
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"{ts}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"Eval report: {out_path}")
    print(f"Questions: {report.get('total_questions', 0)}")
    print(f"Avg entity score: {report.get('avg_entity_score', 0):.3f}")
    print(f"Avg retrieval count: {report.get('avg_retrieval_count', 0)}")


def _inspect(doc_id: str):
    from ..schemas.document import SpectrumDocument
    doc = SpectrumDocument.load(PROJECT_ROOT / "data" / "parsed", doc_id)
    if not doc:
        print(f"Document {doc_id} not found in parsed data", file=sys.stderr)
        sys.exit(1)
    print(f"Document: {doc.filename}")
    print(f"Blocks: {doc.block_count}")
    print(f"Pages: {doc.page_count}")
    print(f"Parsed at: {doc.parsed_at}")
    for bt in ["title", "text", "table", "image", "equation", "footnote"]:
        cnt = len(doc.get_blocks_by_type(bt))
        if cnt > 0:
            print(f"  {bt}: {cnt}")
    print(f"\nFirst 3 blocks:")
    for b in doc.blocks[:3]:
        print(f"  [{b.block_type}] p.{b.page_idx}: {b.content[:120]}...")


# ── main ──

def main():
    ap = argparse.ArgumentParser(description="SpectrumClaw RAG CLI")
    sub = ap.add_subparsers(dest="command")

    sp = sub.add_parser("status", help="Show index status")
    sp = sub.add_parser("index", help="Index PDF documents")
    sp.add_argument("--path", type=str, help="Directory containing PDFs")
    sp.add_argument("--incremental", action="store_true", help="Skip already-indexed docs")

    sp = sub.add_parser("reindex", help="Reindex a single document")
    sp.add_argument("--doc-id", type=str, required=True, help="Document ID")

    sp = sub.add_parser("eval", help="Run RAG evaluation")
    sp.add_argument("--output", type=str, help="Output directory for reports")

    sp = sub.add_parser("inspect", help="Inspect a parsed document")
    sp.add_argument("--doc-id", type=str, required=True, help="Document ID")

    args = ap.parse_args()
    if args.command == "status":
        _status()
    elif args.command == "index":
        _index(args.path, args.incremental)
    elif args.command == "reindex":
        _reindex(args.doc_id)
    elif args.command == "eval":
        _eval_cmd(args.output)
    elif args.command == "inspect":
        _inspect(args.doc_id)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
