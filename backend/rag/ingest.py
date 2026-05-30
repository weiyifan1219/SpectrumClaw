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

    # Init full DocumentProcessor pipeline (RAG-Anything aligned)
    import os
    from backend.rag.parsers import create_parser, ParserFactory
    from backend.rag.processors import get_processor
    from backend.rag.processors.table import TableModalProcessor
    from backend.rag.processors.image import ImageModalProcessor
    from backend.rag.context import ContextBuilder
    from backend.rag.pipeline import DocumentProcessor

    parser_name = os.getenv("SPECTRUMCLAW_PARSER", "pypdf")
    parser = create_parser(parser_name, "pypdf")
    print(f"Parser: {parser.name} (available: {ParserFactory.list_available()})")

    ctx_builder = ContextBuilder(window_size=2)
    text_proc = get_processor("text")
    table_proc = get_processor("table")
    footnote_proc = get_processor("footnote")
    eq_proc = get_processor("equation")

    # VLM client (Qwen-VL)
    image_proc = get_processor("image")
    vlm = None
    if os.getenv("QWEN_VL_API_KEY"):
        from backend.rag.multimodal import QwenVLClient
        vlm = QwenVLClient()
        image_proc = ImageModalProcessor(vlm_client=vlm)
        table_proc = TableModalProcessor()  # LLM-enhanced table in async path
        print(f"VLM: Qwen-VL enabled ({os.getenv('QWEN_VL_MODEL', 'qwen-vl-max')})")
    else:
        print("VLM: not configured (set QWEN_VL_API_KEY)")

    # LLM chat function for entity extraction
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
        print(f"LLM extraction: enabled ({provider.model})")
    except Exception:
        print("LLM extraction: not available")

    chroma_dir = PROJECT_ROOT / "data" / "chroma"
    print("Loading embedding model ...")
    emb = SentenceTransformersEmbeddingProvider()
    store = ChromaStore(persist_dir=chroma_dir, embedding_provider=emb)

    # Build DocumentProcessor (full RAG-Anything aligned pipeline)
    doc_processor = DocumentProcessor(
        parser=parser,
        text_proc=text_proc,
        table_proc=table_proc,
        image_proc=image_proc,
        equation_proc=eq_proc,
        footnote_proc=footnote_proc,
        context_builder=ctx_builder,
        vector_store=store,
        llm_chat_func=llm_chat,
        max_concurrent=int(os.getenv("RAG_MAX_CONCURRENT", "3")),
    )

    if clear:
        print("Clearing existing index ...")
        store.clear()

    parsed_dir = PROJECT_ROOT / "data" / "parsed"
    parsed_dir.mkdir(parents=True, exist_ok=True)

    import asyncio
    total_blocks = 0
    total_docs = 0
    total_entities = 0
    total_relations = 0
    errors = []

    for i, fp in enumerate(pdf_paths):
        try:
            result = asyncio.run(doc_processor.process_document(fp))
        except Exception as exc:
            errors.append({"file": fp, "error": str(exc)})
            continue

        total_docs += 1
        total_blocks += result.text_blocks + result.multimodal_items
        total_entities += result.entities_added
        total_relations += result.relations_added

        if result.errors:
            errors.append({"file": fp, "errors": result.errors})

        if (i + 1) % 50 == 0:
            print(f"  [{i + 1}/{len(pdf_paths)}] {Path(fp).name} "
                  f"({result.text_blocks}t + {result.multimodal_items}m blocks) "
                  f"— {store.count()} vectors total")

    vec_count = store.count()

    summary = {
        "total_pdfs": total_docs,
        "total_blocks": total_blocks,
        "vector_count": vec_count,
        "chroma_dir": str(chroma_dir),
        "graph_entities": total_entities,
        "graph_relations": total_relations,
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
