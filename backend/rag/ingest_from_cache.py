"""Batch ingest from MinerU preparse cache → Chroma + Knowledge Graph.

Reads content_list.json from data/mineru_cache/, converts to
SpectrumContentBlocks, embeds with bge-m3, stores in ChromaDB, and
extracts entities for the knowledge graph.

This avoids re-parsing PDFs and directly uses the GPU-accelerated
preparse results.

Usage:
    python -m backend.rag.ingest_from_cache
    python -m backend.rag.ingest_from_cache --limit 100
    python -m backend.rag.ingest_from_cache --clear
    python -m backend.rag.ingest_from_cache --skip-graph  # skip LLM entity extraction
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.rag.paths import CHROMA_DIR, GRAPH_PATH, DATA_DIR


CACHE_DIR = DATA_DIR / "mineru_cache"


def _discover_cached_docs() -> list[dict]:
    """Find all valid cached content_list.json files."""
    docs = []
    if not CACHE_DIR.exists():
        return docs
    for doc_dir in sorted(CACHE_DIR.iterdir()):
        if not doc_dir.is_dir():
            continue
        content_path = doc_dir / "content_list.json"
        meta_path = doc_dir / "metadata.json"
        if content_path.exists() and meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text())
                docs.append({
                    "doc_id": doc_dir.name,
                    "content_path": str(content_path),
                    "metadata": meta,
                })
            except Exception:
                continue
    return docs


def _load_content_list(content_path: str) -> list[dict]:
    return json.loads(Path(content_path).read_text())


def _content_to_blocks(content_list: list[dict], doc_id: str, source_path: str):
    """Convert MinerU content_list items to SpectrumContentBlocks."""
    from backend.rag.schemas.block import SpectrumContentBlock

    blocks = []
    for item in content_list:
        btype = item.get("type", "text")
        if btype in ("page_number",):
            continue

        text = item.get("text", "")
        page_idx = item.get("page_idx", 0) + 1
        bbox = item.get("bbox")

        block = SpectrumContentBlock.create(
            doc_id=doc_id,
            source_path=source_path,
            page_idx=page_idx,
            block_type=btype,
            raw_content=text,
            content=text,
            caption=item.get("table_caption", item.get("image_caption", [])),
            bbox=bbox,
            asset_path=item.get("img_path", ""),
            parser_name="mineru",
            parser_version="1.0.0",
            metadata={"parser": "mineru", "source_type": btype},
        )
        blocks.append(block)

    return blocks


def _build_embedding_provider():
    """Build the embedding provider (bge-m3 preferred)."""
    from backend.rag.embeddings.sentence_transformer import SentenceTransformersEmbeddingProvider
    device = os.getenv("SPECTRUMCLAW_EMBEDDING_DEVICE", "cuda")
    return SentenceTransformersEmbeddingProvider(device=device)


def _build_chroma_store(embedding_provider):
    from backend.rag.vectorstores.chroma_store import ChromaStore
    return ChromaStore(persist_dir=CHROMA_DIR, embedding_provider=embedding_provider)


def _separate_content(blocks):
    """Split into text and multimodal blocks."""
    text_blocks = []
    multimodal_items = []
    for b in blocks:
        if b.block_type in ("text", "title"):
            text_blocks.append(b)
        else:
            multimodal_items.append(b)
    return text_blocks, multimodal_items


def _extract_entities_batch(text_blocks, doc_id: str, source_path: str):
    """Simple rule-based entity extraction for frequency bands and ITU refs.

    Avoids LLM cost for batch processing. LLM extraction can run separately.
    """
    import re
    from backend.rag.schemas.graph import SpectrumEntity, SpectrumRelation

    entities = []
    relations = []

    freq_pattern = re.compile(
        r'(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)\s*(MHz|GHz|kHz|THz)',
        re.IGNORECASE
    )
    itu_pattern = re.compile(r'ITU-R\s+[A-Z]\.\d+(?:\.\d+)?(?:-\d+)?')
    footnote_pattern = re.compile(r'\b5\.\d{3}[A-Z]?\b')

    seen_entities = set()

    for block in text_blocks:
        text = block.content or ""

        for match in freq_pattern.finditer(text):
            name = match.group(0)
            if name not in seen_entities:
                seen_entities.add(name)
                entities.append(SpectrumEntity(
                    name=name, type="FrequencyBand",
                    evidence_block_id=block.block_id,
                    confidence=0.9, extractor="regex",
                    metadata={"doc_id": doc_id, "source_path": source_path},
                ))

        for match in itu_pattern.finditer(text):
            name = match.group(0)
            if name not in seen_entities:
                seen_entities.add(name)
                entities.append(SpectrumEntity(
                    name=name, type="Standard",
                    evidence_block_id=block.block_id,
                    confidence=0.95, extractor="regex",
                    metadata={"doc_id": doc_id, "source_path": source_path},
                ))

        for match in footnote_pattern.finditer(text):
            name = match.group(0)
            if name not in seen_entities:
                seen_entities.add(name)
                entities.append(SpectrumEntity(
                    name=name, type="Footnote",
                    evidence_block_id=block.block_id,
                    confidence=0.9, extractor="regex",
                    metadata={"doc_id": doc_id, "source_path": source_path},
                ))

    # Add document entity
    doc_entity_name = Path(source_path).stem
    entities.append(SpectrumEntity(
        name=doc_entity_name, type="Document",
        evidence_block_id="",
        confidence=1.0, extractor="system",
        metadata={"doc_id": doc_id, "source_path": source_path},
    ))

    # belongs_to relations
    for ent in entities:
        if ent.type != "Document":
            relations.append(SpectrumRelation(
                source=ent.name, relation="mentioned_in",
                target=doc_entity_name,
                evidence_block_id=ent.evidence_block_id,
                confidence=0.85, extractor="regex",
                doc_id=doc_id, page_idx=0, source_path=source_path,
            ))

    return entities, relations


def _merge_graph(entities, relations):
    """Merge entities and relations into the graph JSON."""
    existing = {"entities": [], "relations": [], "entity_count": 0, "relation_count": 0}
    if GRAPH_PATH.exists():
        try:
            existing = json.loads(GRAPH_PATH.read_text())
        except Exception:
            pass

    entity_map = {}
    for e in existing.get("entities", []):
        key = (e.get("name", ""), e.get("type", ""))
        entity_map[key] = e
    for e in entities:
        key = (e.name, e.type)
        if key not in entity_map:
            entity_map[key] = e.to_dict()

    rel_set = set()
    for r in existing.get("relations", []):
        key = (r.get("source", ""), r.get("relation", ""), r.get("target", ""))
        rel_set.add(key)
    new_rels = []
    for r in relations:
        key = (r.source, r.relation, r.target)
        if key not in rel_set:
            rel_set.add(key)
            new_rels.append(r.to_dict())

    graph = {
        "entities": list(entity_map.values()),
        "relations": existing.get("relations", []) + new_rels,
        "entity_count": len(entity_map),
        "relation_count": len(existing.get("relations", [])) + len(new_rels),
    }
    GRAPH_PATH.parent.mkdir(parents=True, exist_ok=True)
    GRAPH_PATH.write_text(json.dumps(graph, ensure_ascii=False, indent=2))
    return graph["entity_count"], graph["relation_count"]


def main():
    ap = argparse.ArgumentParser(description="Ingest from MinerU cache to Chroma + Graph")
    ap.add_argument("--limit", type=int, help="Max docs to process")
    ap.add_argument("--clear", action="store_true", help="Clear Chroma before ingest")
    ap.add_argument("--skip-graph", action="store_true", help="Skip entity extraction")
    ap.add_argument("--batch-size", type=int, default=50, help="Embedding batch size")
    args = ap.parse_args()

    print("[*] Discovering cached documents...")
    cached_docs = _discover_cached_docs()
    print(f"    Found {len(cached_docs)} cached documents")

    if not cached_docs:
        print("No cached documents found. Run preparse_gpu first.")
        sys.exit(1)

    if args.limit:
        cached_docs = cached_docs[:args.limit]
        print(f"    Limited to {len(cached_docs)} documents")

    print("[*] Loading embedding model (bge-m3)...")
    t0 = time.time()
    emb = _build_embedding_provider()
    store = _build_chroma_store(emb)
    print(f"    Embedding model loaded in {time.time() - t0:.1f}s")

    if args.clear:
        store.clear()
        print("[*] Cleared existing Chroma index")
        if GRAPH_PATH.exists():
            GRAPH_PATH.write_text(json.dumps(
                {"entities": [], "relations": [], "entity_count": 0, "relation_count": 0}
            ))
            print("[*] Cleared graph")

    # Check already indexed
    from backend.rag.doc_registry import register_doc, update_status, is_cached as doc_is_cached

    total_blocks = 0
    total_entities = 0
    total_relations = 0
    total_docs = 0
    errors = []
    skipped = 0

    started = time.time()

    for i, doc_info in enumerate(cached_docs):
        doc_id = doc_info["doc_id"]
        meta = doc_info["metadata"]
        source_path = meta.get("source_path", "")
        filename = meta.get("filename", doc_id)

        # Skip already indexed
        if not args.clear and doc_is_cached(source_path, "mineru", "1.0.0"):
            skipped += 1
            continue

        try:
            content_list = _load_content_list(doc_info["content_path"])
            blocks = _content_to_blocks(content_list, doc_id, source_path)

            if not blocks:
                continue

            text_blocks, multimodal_items = _separate_content(blocks)

            # Register in doc_registry
            registry_id = register_doc(
                source_path, parser_name="mineru", parser_version="1.0.0", status="indexing"
            )

            # Embed and store text blocks
            if text_blocks:
                store.add_blocks(text_blocks)

            # Embed multimodal blocks that have content
            mm_with_content = [b for b in multimodal_items if b.content]
            if mm_with_content:
                store.add_blocks(mm_with_content)

            total_blocks += len(text_blocks) + len(mm_with_content)

            # Entity extraction (regex-based for speed)
            if not args.skip_graph:
                ents, rels = _extract_entities_batch(text_blocks, doc_id, source_path)
                if ents or rels:
                    _merge_graph(ents, rels)
                    total_entities += len(ents)
                    total_relations += len(rels)

            update_status(registry_id, "indexed")
            total_docs += 1

        except Exception as exc:
            errors.append({"file": filename, "error": str(exc)[:200]})
            continue

        if (i + 1) % 50 == 0:
            elapsed = time.time() - started
            rate = total_docs / max(elapsed, 1) * 60
            vec_count = store.count()
            print(f"  [{i + 1}/{len(cached_docs)}] "
                  f"{total_docs} indexed, {skipped} skipped, "
                  f"{vec_count} vectors, "
                  f"{total_entities} entities, "
                  f"{rate:.0f} docs/min")

    elapsed = time.time() - started
    vec_count = store.count()

    print(f"\n{'='*60}")
    print(f"Ingest complete in {elapsed:.0f}s")
    print(f"  Documents indexed:  {total_docs}")
    print(f"  Documents skipped:  {skipped}")
    print(f"  Total blocks:       {total_blocks}")
    print(f"  Vectors in Chroma:  {vec_count}")
    print(f"  Graph entities:     {total_entities}")
    print(f"  Graph relations:    {total_relations}")
    print(f"  Errors:             {len(errors)}")
    if errors:
        for e in errors[:5]:
            print(f"    - {e['file']}: {e['error']}")


if __name__ == "__main__":
    main()
