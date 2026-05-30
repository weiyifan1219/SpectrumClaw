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


def _build_doc_processor():
    """Shared factory: build a DocumentProcessor with all configured components.

    Used by both CLI (ingest) and API (/api/rag/index) to ensure the same pipeline.
    """
    import os
    from backend.rag.parsers import create_parser, ParserFactory
    from backend.rag.processors import get_processor
    from backend.rag.processors.table import TableModalProcessor
    from backend.rag.processors.image import ImageModalProcessor
    from backend.rag.context import ContextBuilder
    from backend.rag.pipeline import DocumentProcessor
    from backend.rag.embeddings.sentence_transformer import SentenceTransformersEmbeddingProvider
    from backend.rag.vectorstores.chroma_store import ChromaStore
    from backend.rag.paths import CHROMA_DIR

    parser_name = os.getenv("SPECTRUMCLAW_PARSER", "pypdf")
    parser = create_parser(parser_name, "pypdf")

    ctx_builder = ContextBuilder(window_size=2)
    text_proc = get_processor("text")
    table_proc = get_processor("table")
    footnote_proc = get_processor("footnote")
    eq_proc = get_processor("equation")
    image_proc = get_processor("image")

    if os.getenv("QWEN_VL_API_KEY"):
        from backend.rag.multimodal import QwenVLClient
        vlm = QwenVLClient()
        image_proc = ImageModalProcessor(vlm_client=vlm)
        table_proc = TableModalProcessor()

    llm_chat = None
    try:
        from backend.config import get_settings
        from backend.llm.client import chat as llm_chat_fn
        settings = get_settings()
        provider = settings.provider_profile()
        async def _chat(msgs):
            reply, _ = await llm_chat_fn(msgs, provider_override=provider.provider,
                                          model_override=provider.model)
            return reply
        llm_chat = _chat
    except Exception:
        pass

    emb = SentenceTransformersEmbeddingProvider()
    store = ChromaStore(persist_dir=CHROMA_DIR, embedding_provider=emb)

    # Callbacks for observability (optional — emits progress events)
    callbacks = None
    try:
        from backend.rag.callbacks import CallbackManager
        callbacks = CallbackManager()
    except Exception:
        pass

    return DocumentProcessor(
        parser=parser, text_proc=text_proc, table_proc=table_proc,
        image_proc=image_proc, equation_proc=eq_proc, footnote_proc=footnote_proc,
        context_builder=ctx_builder, vector_store=store, llm_chat_func=llm_chat,
        max_concurrent=int(os.getenv("RAG_MAX_CONCURRENT", "3")),
        callbacks=callbacks,
    )


def _resolve_pdf_paths(pdf_paths: list[str] | None = None) -> list[str] | dict:
    """Resolve explicit paths or discover PDFs from the project data folders."""
    if pdf_paths is not None:
        return pdf_paths

    upload_dir = PROJECT_ROOT / "data" / "uploads"
    if upload_dir.exists():
        paths = sorted(str(p) for p in upload_dir.glob("*.pdf"))
        if paths:
            return paths

    raw_dir = PROJECT_ROOT / "data" / "knowledge_base" / "raw"
    if raw_dir.exists():
        paths = sorted(str(p) for p in raw_dir.glob("*.pdf"))
        if paths:
            return paths

    return {"error": "No PDFs found. Place files in data/uploads/ or data/knowledge_base/raw/"}


async def index_documents(
    pdf_paths: list[str] | None = None,
    clear: bool = False,
    limit: int | None = None,
    use_cache: bool = True,
) -> dict:
    """Run the shared RAG indexing pipeline.

    Steps:
      1. Parse PDFs → SpectrumDocument (PyPDFParser)
      2. Process blocks → enhanced_content (TextProcessor, TableProcessor)
      3. Embed blocks → SentenceTransformersEmbeddingProvider
      4. Store → ChromaStore
      5. Save content_list.json per document
    """
    resolved_paths = _resolve_pdf_paths(pdf_paths)
    if isinstance(resolved_paths, dict):
        return resolved_paths
    pdf_paths = resolved_paths

    if not pdf_paths:
        return {"error": "No PDF files found to index."}

    if limit:
        pdf_paths = pdf_paths[:limit]

    total_attempted = len(pdf_paths)
    print(f"Found {len(pdf_paths)} PDFs to process")
    doc_processor = _build_doc_processor()

    import os
    from backend.rag.parsers import ParserFactory
    from backend.rag.paths import CHROMA_DIR
    from backend.rag.doc_registry import register_doc, update_status, get_unindexed

    parser_name = os.getenv("SPECTRUMCLAW_PARSER", "pypdf")

    if clear:
        if doc_processor.vector_store:
            doc_processor.vector_store.clear()
        print("Cleared existing index")
    elif use_cache:
        # Skip already-indexed files only for incremental runs. A clear run must
        # rebuild all requested files, otherwise it can empty Chroma and index none.
        unindexed_paths = get_unindexed(pdf_paths, parser_name, doc_processor.parser.version)
        skip_count = len(pdf_paths) - len(unindexed_paths)
        if skip_count > 0:
            print(f"Skipping {skip_count} already-indexed files (use --clear to force rebuild)")
        pdf_paths = unindexed_paths

    print(f"Parser: {doc_processor.parser.name} (available: {ParserFactory.list_available()})")
    print(f"VLM: {'enabled' if os.getenv('QWEN_VL_API_KEY') else 'not configured'}")
    print(f"LLM extraction: {'enabled' if doc_processor.llm_chat else 'not available'}")

    total_blocks = 0
    total_docs = 0
    total_entities = 0
    total_relations = 0
    errors = []

    for i, fp in enumerate(pdf_paths):
        registry_id = register_doc(
            fp,
            parser_name=parser_name,
            parser_version=doc_processor.parser.version,
            status="indexing",
        )

        try:
            result = await doc_processor.process_document(fp)
        except Exception as exc:
            error = str(exc)
            errors.append({"file": fp, "error": error})
            update_status(registry_id, "failed", error)
            continue

        total_docs += 1
        total_blocks += result.text_blocks + result.multimodal_items
        total_entities += result.entities_added
        total_relations += result.relations_added

        if result.errors:
            errors.append({"file": fp, "errors": result.errors})
            update_status(registry_id, "failed", "; ".join(result.errors))
        else:
            update_status(registry_id, "indexed")

        vc = doc_processor.vector_store.count() if doc_processor.vector_store else 0
        if (i + 1) % 50 == 0:
            print(f"  [{i + 1}/{len(pdf_paths)}] {Path(fp).name} "
                  f"({result.text_blocks}t + {result.multimodal_items}m blocks) "
                  f"— {vc} vectors total")

    vec_count = doc_processor.vector_store.count() if doc_processor.vector_store else 0

    summary = {
        "total_pdfs": total_docs,
        "total_attempted": total_attempted,
        "total_blocks": total_blocks,
        "vector_count": vec_count,
        "chroma_dir": str(CHROMA_DIR),
        "graph_entities": total_entities,
        "graph_relations": total_relations,
        "errors": errors,
    }
    print(f"\nDone: {json.dumps({k: v for k, v in summary.items() if k != 'errors'}, ensure_ascii=False)}")
    if errors:
        print(f"Errors: {len(errors)} files skipped")
    return summary


def ingest(
    pdf_paths: list[str] | None = None,
    clear: bool = False,
    limit: int | None = None,
) -> dict:
    """Synchronous CLI wrapper for the shared async RAG indexing pipeline."""
    import asyncio

    return asyncio.run(index_documents(pdf_paths=pdf_paths, clear=clear, limit=limit))


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
