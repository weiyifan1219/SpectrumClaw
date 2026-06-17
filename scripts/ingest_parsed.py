#!/usr/bin/env python3
"""Ingest parsed MinerU content_list.json files into ChromaDB.

Reads from data/parsed/<stem>/<stem>/auto/<stem>_content_list.json,
filters by block type, embeds text content, stores in ChromaDB.

Usage:
    CUDA_VISIBLE_DEVICES=1 SPECTRUMCLAW_EMBEDDING_DEVICE=cuda \
    python scripts/ingest_parsed.py [--clear] [--limit N]
"""

import argparse
import hashlib
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

PARSED_DIR = PROJECT_ROOT / "data" / "parsed"
CHROMA_DIR = PROJECT_ROOT / "data" / "chroma"
GRAPH_PATH = PROJECT_ROOT / "data" / "graph" / "spectrum_graph.json"

# Block types to embed
EMBED_TYPES = {"text", "equation", "table", "chart", "page_footnote", "list", "aside_text"}
# Block types to skip
SKIP_TYPES = {"header", "footer", "page_number", "image"}


def extract_text(item: dict) -> str:
    """Extract embeddable text from a content_list item."""
    btype = item.get("type", "")

    if btype in ("text", "equation", "page_footnote", "aside_text"):
        return item.get("text", "")
    elif btype == "list":
        # list has list_items
        items = item.get("list_items", [])
        if isinstance(items, list):
            return "\n".join(str(li) for li in items)
        return str(items)
    elif btype == "table":
        # Prefer table_body (HTML), fallback to caption
        body = item.get("table_body", "")
        caption = " ".join(item.get("table_caption", []))
        footnote = " ".join(item.get("table_footnote", []))
        parts = [p for p in [caption, body, footnote] if p]
        return "\n".join(parts)
    elif btype == "chart":
        # chart content (VLM description) or caption
        content = item.get("content", "")
        caption = " ".join(item.get("chart_caption", []))
        return content or caption
    return ""


def make_block_id(source_path: str, page_idx: int, idx: int) -> str:
    raw = f"{source_path}:{page_idx}:{idx}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def discover_content_lists() -> list[tuple[str, Path]]:
    """Find all content_list.json files in parsed directory."""
    results = []
    for cl_file in sorted(PARSED_DIR.rglob("*_content_list.json")):
        # Skip v2 files
        if "_content_list_v2.json" in cl_file.name:
            continue
        # Derive source filename from directory structure
        # Structure: data/parsed/<stem>/<stem>/auto/<stem>_content_list.json
        stem = cl_file.stem.replace("_content_list", "")
        results.append((stem, cl_file))
    return results


def main():
    ap = argparse.ArgumentParser(description="Ingest parsed content into ChromaDB")
    ap.add_argument("--clear", action="store_true", help="Clear existing ChromaDB before ingest")
    ap.add_argument("--limit", type=int, help="Limit number of documents to process")
    ap.add_argument("--batch-size", type=int, default=256, help="Embedding batch size")
    args = ap.parse_args()

    from backend.rag.embeddings.sentence_transformer import SentenceTransformersEmbeddingProvider
    from backend.rag.vectorstores.chroma_store import ChromaStore

    print("Loading embedding model...", flush=True)
    emb = SentenceTransformersEmbeddingProvider()
    store = ChromaStore(persist_dir=str(CHROMA_DIR), embedding_provider=emb)

    if args.clear:
        store.clear()
        print("ChromaDB cleared.", flush=True)

    content_lists = discover_content_lists()
    if args.limit:
        content_lists = content_lists[:args.limit]

    print(f"Found {len(content_lists)} parsed documents.", flush=True)

    total_embedded = 0
    total_skipped = 0
    type_stats = Counter()
    errors = []
    start_time = time.time()

    for doc_idx, (stem, cl_path) in enumerate(content_lists, 1):
        try:
            data = json.loads(cl_path.read_text())
        except Exception as e:
            errors.append({"file": stem, "error": str(e)})
            continue

        # Find source PDF path
        source_pdf = ""
        for pdf in (PROJECT_ROOT / "data" / "knowledge_base" / "raw").glob(f"{stem}*.pdf"):
            source_pdf = str(pdf)
            break

        texts = []
        ids = []
        metadatas = []

        for idx, item in enumerate(data):
            btype = item.get("type", "")
            type_stats[btype] += 1

            if btype not in EMBED_TYPES:
                total_skipped += 1
                continue

            text = extract_text(item)
            if not text or len(text.strip()) < 10:
                total_skipped += 1
                continue

            page_idx = item.get("page_idx", 0)
            block_id = make_block_id(source_pdf or stem, page_idx, idx)

            texts.append(text)
            ids.append(block_id)
            metadatas.append({
                "source_path": source_pdf,
                "doc_id": stem,
                "page_idx": page_idx,
                "block_type": btype,
                "parser": "mineru",
                "source_type": btype,
            })

        if texts:
            # Embed in batches
            batch_size = args.batch_size
            for i in range(0, len(texts), batch_size):
                batch_texts = texts[i:i+batch_size]
                batch_ids = ids[i:i+batch_size]
                batch_metas = metadatas[i:i+batch_size]

                embeddings = emb.embed_texts(batch_texts)
                col = store._get_collection()
                col.add(
                    ids=batch_ids,
                    embeddings=embeddings,
                    metadatas=batch_metas,
                    documents=batch_texts,
                )

            total_embedded += len(texts)

        if doc_idx % 100 == 0:
            elapsed = time.time() - start_time
            rate = doc_idx / elapsed * 3600
            print(f"  [{doc_idx}/{len(content_lists)}] {stem} | "
                  f"embedded: {total_embedded}, skipped: {total_skipped} | "
                  f"{rate:.0f} docs/hr", flush=True)

    elapsed = time.time() - start_time
    vec_count = store.count()

    print(f"\n=== Ingest Complete ===", flush=True)
    print(f"Documents: {len(content_lists)}", flush=True)
    print(f"Blocks embedded: {total_embedded}", flush=True)
    print(f"Blocks skipped: {total_skipped}", flush=True)
    print(f"Vector count: {vec_count}", flush=True)
    print(f"Time: {elapsed:.0f}s ({elapsed/60:.1f}min)", flush=True)
    print(f"Block type stats: {dict(type_stats)}", flush=True)
    if errors:
        print(f"Errors: {len(errors)}", flush=True)

    # Update meta.json
    meta_path = PROJECT_ROOT / "data" / "knowledge_base" / "index" / "meta.json"
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "total_pdfs": len(content_lists),
        "total_chunks": vec_count,
        "total_chars": total_embedded * 200,  # approximate
        "block_types": dict(type_stats),
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False))
    print(f"Meta saved to {meta_path}", flush=True)


if __name__ == "__main__":
    main()
