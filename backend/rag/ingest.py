"""RAG ingestion pipeline: parse → process → embed → store.

Replaces the old TF-IDF pipeline with structured parsing and embedding-based indexing.
Usage:
    python -m backend.rag.ingest          # index all PDFs in data/uploads
    python -m backend.rag.ingest --clear  # clear existing index first
    python -m backend.rag.ingest --file <path>  # index a single PDF
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))


def ingest(
    pdf_paths: list[str] | None = None,
    clear: bool = False,
    limit: int | None = None,
) -> dict:
    """Run the full RAG ingestion pipeline.

    Steps:
      1. Parse PDFs → SpectrumDocument (PyPDFParser)
      2. Process blocks → enhanced_content (TextProcessor, TableProcessor)
      3. Embed blocks → SentenceTransformersEmbeddingProvider
      4. Store → ChromaStore
      5. Save content_list.json per document
    """
    from backend.rag.parsers.pypdf_parser import PyPDFParser
    from backend.rag.processors.text import TextProcessor
    from backend.rag.processors.table import TableProcessor
    from backend.rag.embeddings.sentence_transformer import SentenceTransformersEmbeddingProvider
    from backend.rag.vectorstores.chroma_store import ChromaStore
    from backend.rag.graph.entity_extractor import SpectrumEntityExtractor, ExtractionResult

    # Resolve PDFs
    if pdf_paths is None:
        upload_dir = PROJECT_ROOT / "data" / "uploads"
        if not upload_dir.exists():
            # fall back to the old knowledge_base/raw
            raw_dir = PROJECT_ROOT / "data" / "knowledge_base" / "raw"
            if raw_dir.exists():
                pdf_paths = sorted(str(p) for p in raw_dir.glob("*.pdf"))
            else:
                return {"error": "No PDFs found. Place files in data/uploads/ or data/knowledge_base/raw/"}
        else:
            pdf_paths = sorted(str(p) for p in upload_dir.glob("*.pdf"))
            if not pdf_paths:
                raw_dir = PROJECT_ROOT / "data" / "knowledge_base" / "raw"
                if raw_dir.exists():
                    pdf_paths = sorted(str(p) for p in raw_dir.glob("*.pdf"))

    if not pdf_paths:
        return {"error": "No PDF files found to index."}

    if limit:
        pdf_paths = pdf_paths[:limit]

    print(f"Found {len(pdf_paths)} PDFs to process")

    # Init components — v2 parser factory + processors + context
    from backend.rag.parsers import create_parser
    from backend.rag.processors import get_processor, process_block
    from backend.rag.processors.table import TableModalProcessor
    from backend.rag.context import ContextBuilder

    parser = create_parser("pypdf", "pypdf")
    text_proc = get_processor("text")
    table_proc = get_processor("table")
    footnote_proc = get_processor("footnote")
    ctx_builder = ContextBuilder(window_size=2)

    chroma_dir = PROJECT_ROOT / "data" / "chroma"
    print(f"Loading embedding model ...")
    emb = SentenceTransformersEmbeddingProvider()
    store = ChromaStore(persist_dir=chroma_dir, embedding_provider=emb)

    if clear:
        print("Clearing existing index ...")
        store.clear()

    parsed_dir = PROJECT_ROOT / "data" / "parsed"
    parsed_dir.mkdir(parents=True, exist_ok=True)

    total_blocks = 0
    total_docs = 0
    errors = []

    # Entity extraction for knowledge graph
    entity_extractor = SpectrumEntityExtractor()
    all_entities: list[dict] = []
    all_relations: list[dict] = []
    seen_entities: set[tuple] = set()  # (name, type) dedup

    for i, fp in enumerate(pdf_paths):
        try:
            doc = parser.parse(fp)
        except Exception as exc:
            errors.append({"file": fp, "error": str(exc)})
            continue

        # Process blocks with modality-aware dispatch + context
        for j, block in enumerate(doc.blocks):
            ctx = ctx_builder.build_from_blocks(doc.blocks, j)
            if block.block_type in ("table",):
                table_proc.process(block, ctx)
            elif block.block_type == "footnote":
                footnote_proc.process(block, ctx)
            else:
                text_proc.process(block, ctx)

        total_blocks += len(doc.blocks)
        total_docs += 1

        # Save parsed output (v2 schema)
        doc.save(parsed_dir, save_assets=True)

        # Embed and store in batches
        if doc.blocks:
            store.add_blocks(doc.blocks)

            # Extract entities for knowledge graph
            for block in doc.blocks:
                text = block.enhanced_content or block.content
                extraction = entity_extractor.extract(text, block.block_id)
                for e in extraction.entities:
                    key = (e.name, e.type)
                    if key not in seen_entities:
                        seen_entities.add(key)
                        all_entities.append(e.to_dict())
                for r in extraction.relations:
                    all_relations.append(r.to_dict())

        if (i + 1) % 50 == 0:
            print(f"  [{i + 1}/{len(pdf_paths)}] {doc.filename} ({len(doc.blocks)} blocks) — {store.count()} vectors total")

    vec_count = store.count()

    # Save knowledge graph
    graph_dir = PROJECT_ROOT / "data" / "graph"
    graph_dir.mkdir(parents=True, exist_ok=True)
    graph_data = {
        "entities": all_entities,
        "relations": all_relations,
        "entity_count": len(all_entities),
        "relation_count": len(all_relations),
    }
    (graph_dir / "spectrum_graph.json").write_text(
        json.dumps(graph_data, ensure_ascii=False, indent=2),
    )
    print(f"Graph: {len(all_entities)} entities, {len(all_relations)} relations")

    summary = {
        "total_pdfs": total_docs,
        "total_blocks": total_blocks,
        "vector_count": vec_count,
        "chroma_dir": str(chroma_dir),
        "graph_entities": len(all_entities),
        "graph_relations": len(all_relations),
        "errors": errors,
    }
    print(f"\nDone: {json.dumps({k: v for k, v in summary.items() if k != 'errors'}, ensure_ascii=False)}")
    if errors:
        print(f"Errors: {len(errors)} files skipped")
    return summary


def main():
    ap = argparse.ArgumentParser(description="RAG ingest pipeline")
    ap.add_argument("--file", type=str, help="Index a single PDF file")
    ap.add_argument("--dir", type=str, help="Index all PDFs in a directory")
    ap.add_argument("--clear", action="store_true", help="Clear existing index before ingest")
    ap.add_argument("--limit", type=int, help="Max number of PDFs to process")
    args = ap.parse_args()

    if args.file:
        pdf_paths = [args.file]
    elif args.dir:
        pdf_paths = sorted(str(p) for p in Path(args.dir).glob("*.pdf"))
    else:
        pdf_paths = None

    result = ingest(pdf_paths=pdf_paths, clear=args.clear, limit=args.limit)
    if "error" in result:
        print(f"ERROR: {result['error']}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
