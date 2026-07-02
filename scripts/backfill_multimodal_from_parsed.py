#!/usr/bin/env python3
"""Backfill multimodal parsed MinerU outputs into Chroma + graph.

This reuses the existing `data/parsed/<doc>/<doc>/auto/*_content_list.json`
artifacts that were produced by MinerU, resolves their `images/...` assets,
and runs the current table/image/chart/equation processors so non-text chunks
can be embedded into Chroma without reparsing the original PDFs.
"""

from __future__ import annotations

import argparse
import asyncio
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
TARGET_TYPES = {"image", "chart", "equation", "table"}
TEXT_TYPES = {"text", "title", "page_footnote", "footnote", "list", "aside_text"}


def load_env_file() -> None:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = value.strip().strip('"').strip("'")


def normalize_text_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(part).strip() for part in value if str(part).strip()]
    text = str(value).strip()
    return [text] if text else []


def join_text_parts(*parts) -> str:
    flattened: list[str] = []
    for part in parts:
        if part is None:
            continue
        if isinstance(part, list):
            flattened.extend(str(entry).strip() for entry in part if str(entry).strip())
        else:
            text = str(part).strip()
            if text:
                flattened.append(text)
    return "\n".join(flattened)


def extract_text(item: dict) -> str:
    btype = item.get("type", "")
    if btype in ("text", "title", "equation", "page_footnote", "footnote", "aside_text"):
        return str(item.get("text", "") or "")
    if btype == "list":
        return join_text_parts(item.get("text"), item.get("list_items", []))
    if btype == "table":
        return join_text_parts(
            item.get("text"),
            item.get("table_caption", []),
            item.get("table_body", ""),
            item.get("table_footnote", []),
        )
    if btype == "chart":
        return join_text_parts(
            item.get("text"),
            item.get("content", ""),
            item.get("chart_caption", []),
            item.get("table_caption", []),
        )
    if btype == "image":
        return join_text_parts(
            item.get("text"),
            item.get("image_caption", []),
            item.get("caption", []),
        )
    return str(item.get("text", "") or "")


def resolve_asset_path(item: dict, auto_dir: Path) -> str:
    raw_path = item.get("image_path") or item.get("img_path") or ""
    if not raw_path:
        return ""
    asset_path = Path(raw_path)
    if not asset_path.is_absolute():
        asset_path = auto_dir / asset_path
    return str(asset_path.resolve()) if asset_path.exists() else ""


def make_block_id(source_path: str, page_idx: int, idx: int, flavor: str = "") -> str:
    raw = f"{source_path}:{page_idx}:{idx}"
    if flavor:
        raw = f"{raw}:{flavor}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def discover_content_lists() -> list[tuple[str, Path]]:
    results = []
    for cl_file in sorted(PARSED_DIR.rglob("*_content_list.json")):
        if "_content_list_v2.json" in cl_file.name:
            continue
        stem = cl_file.stem.replace("_content_list", "")
        results.append((stem, cl_file))
    return results


def build_source_pdf_map() -> dict[str, str]:
    raw_dir = PROJECT_ROOT / "data" / "knowledge_base" / "raw"
    mapping: dict[str, str] = {}
    if not raw_dir.exists():
        return mapping
    for pdf in raw_dir.glob("*.pdf"):
        mapping.setdefault(pdf.stem, str(pdf.resolve()))
    return mapping


def build_blocks(stem: str, cl_path: Path, data: list[dict], pdf_map: dict[str, str]):
    from backend.rag.schemas.block import SpectrumContentBlock

    source_pdf = pdf_map.get(stem, "")
    source_ref = source_pdf or str(cl_path.resolve())
    auto_dir = cl_path.parent
    blocks = []
    missing_assets = 0

    for idx, item in enumerate(data):
        btype = item.get("type", "text")
        page_idx = int(item.get("page_idx", 0)) + 1
        asset_path = resolve_asset_path(item, auto_dir)
        if (item.get("image_path") or item.get("img_path")) and not asset_path:
            missing_assets += 1

        caption = (
            normalize_text_list(item.get("table_caption"))
            or normalize_text_list(item.get("chart_caption"))
            or normalize_text_list(item.get("image_caption"))
            or normalize_text_list(item.get("caption"))
        )
        footnote = normalize_text_list(item.get("table_footnote")) or normalize_text_list(item.get("footnote"))
        raw_content = extract_text(item)

        block = SpectrumContentBlock.create(
            doc_id=stem,
            source_path=source_ref,
            page_idx=page_idx,
            block_type=btype,
            raw_content=raw_content,
            content=raw_content,
            caption=caption,
            bbox=item.get("bbox"),
            asset_path=asset_path or None,
            parser_name="mineru",
            parser_version="parsed_auto_v1",
            metadata={
                "parser": "mineru",
                "source_type": btype,
                "parsed_content_path": str(cl_path.resolve()),
                "parsed_auto_dir": str(auto_dir.resolve()),
                "original_asset_path": item.get("image_path") or item.get("img_path") or "",
            },
        )
        block.block_id = make_block_id(source_ref, page_idx, idx, flavor=f"mm:{btype}")
        if footnote:
            block.footnote = footnote
        blocks.append(block)

    return blocks, missing_assets


def add_blocks_if_missing(store, blocks, *, min_chars: int = 20) -> tuple[int, int]:
    if not blocks:
        return 0, 0

    clean_blocks = [
        block
        for block in blocks
        if not store._is_junk_chunk(block.enhanced_content or block.content, min_chars=min_chars)
    ]
    if not clean_blocks:
        return 0, 0

    col = store._get_collection()
    inserted = 0
    skipped_existing = 0
    batch_size = 200

    for offset in range(0, len(clean_blocks), batch_size):
        batch_blocks = clean_blocks[offset:offset + batch_size]
        batch_ids = [block.block_id for block in batch_blocks]
        existing_resp = col.get(ids=batch_ids, include=[])
        existing_ids = set(existing_resp.get("ids") or [])
        pending = [block for block in batch_blocks if block.block_id not in existing_ids]
        skipped_existing += len(batch_blocks) - len(pending)
        if not pending:
            continue

        texts = [block.enhanced_content or block.content for block in pending]
        embeddings = store._embedding_provider.embed_texts(texts)
        metadatas = [store._block_metadata(block) for block in pending]
        col.add(
            ids=[block.block_id for block in pending],
            embeddings=embeddings,
            metadatas=metadatas,
            documents=texts,
        )
        inserted += len(pending)

    return inserted, skipped_existing


async def process_multimodal_doc(
    stem: str,
    cl_path: Path,
    *,
    data: list[dict],
    pdf_map: dict[str, str],
    doc_processor,
    target_types: set[str],
    graph_llm: bool,
):
    from backend.rag.pipeline import _merge_into_graph_json
    from backend.rag.processor import build_multimodal_entity_graph
    from backend.rag.schemas.graph import SpectrumEntity

    blocks, missing_assets = build_blocks(stem, cl_path, data, pdf_map)
    block_index = {block.block_id: idx for idx, block in enumerate(blocks)}
    targets = [block for block in blocks if block.block_type in target_types]

    if not targets:
        return {
            "processed": 0,
            "inserted": 0,
            "existing": 0,
            "missing_assets": missing_assets,
            "entities": 0,
            "relations": 0,
            "errors": [],
        }

    proc_map = {
        "table": doc_processor.table_proc,
        "image": doc_processor.image_proc,
        "chart": doc_processor.image_proc,
        "equation": doc_processor.equation_proc,
    }
    llm_for_graph = doc_processor.llm_chat if graph_llm else None
    sem = asyncio.Semaphore(max(int(getattr(doc_processor, "max_concurrent", 3)), 1))

    async def _process_one(item):
        ctx = None
        idx = block_index.get(item.block_id, -1)
        if doc_processor.context_builder and idx >= 0:
            ctx = doc_processor.context_builder.build_from_blocks(blocks, idx)
        proc = proc_map.get(item.block_type)
        async with sem:
            try:
                if proc:
                    if hasattr(proc, "process_async"):
                        await proc.process_async(item, ctx)
                    else:
                        proc.process(item, ctx)
                ents, rels = await build_multimodal_entity_graph(
                    {},
                    item,
                    item.doc_id,
                    item.source_path,
                    llm_for_graph,
                )
                return item, ents, rels, None
            except Exception as exc:
                return item, [], [], str(exc)

    results = await asyncio.gather(*[_process_one(item) for item in targets])

    ready_blocks = []
    all_entities = [
        SpectrumEntity(
            name=f"Document:{stem}",
            type="Document",
            evidence_block_id="",
            confidence=1.0,
            extractor="system",
            metadata={"doc_id": stem, "source_path": pdf_map.get(stem, "")},
        )
    ]
    all_relations = []
    errors = []

    for item, entities, relations, err in results:
        if err:
            errors.append(f"{item.block_type}:{item.block_id}:{err}")
            continue
        if item.enhanced_content:
            ready_blocks.append(item)
        all_entities.extend(entities)
        all_relations.extend(relations)

    inserted, existing = add_blocks_if_missing(doc_processor.vector_store, ready_blocks)
    if all_entities or all_relations:
        _merge_into_graph_json(doc_processor.graph_path, all_entities, all_relations)

    return {
        "processed": len(targets),
        "inserted": inserted,
        "existing": existing,
        "missing_assets": missing_assets,
        "entities": len(all_entities),
        "relations": len(all_relations),
        "errors": errors,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Backfill multimodal parsed outputs into Chroma")
    ap.add_argument("--clear", action="store_true", help="Clear existing Chroma collection before running")
    ap.add_argument("--limit", type=int, help="Limit number of parsed documents to process")
    ap.add_argument(
        "--types",
        default="image,chart,equation,table",
        help="Comma-separated block types to backfill",
    )
    ap.add_argument(
        "--graph-llm",
        action="store_true",
        help="Also run LLM entity extraction on enhanced multimodal content",
    )
    ap.add_argument(
        "--vlm-mode",
        choices=("local", "api", "auto"),
        default="local",
        help="Which VLM backend to use for image/chart/equation enhancement",
    )
    ap.add_argument(
        "--local-vlm-model-path",
        default=str(PROJECT_ROOT / "models" / "MinerU2.5-Pro-2605-1.2B"),
        help="Local Qwen2-VL model directory when --vlm-mode=local",
    )
    args = ap.parse_args()

    load_env_file()
    os.environ["QWEN_VL_MODE"] = args.vlm_mode
    if args.local_vlm_model_path:
        os.environ["QWEN_VL_LOCAL_MODEL_PATH"] = str(Path(args.local_vlm_model_path).expanduser())

    from backend.rag.ingest import _build_doc_processor

    target_types = {part.strip() for part in args.types.split(",") if part.strip()}
    unknown = sorted(target_types - TARGET_TYPES)
    if unknown:
        raise SystemExit(f"Unsupported types: {', '.join(unknown)}")

    content_lists = discover_content_lists()
    if args.limit:
        content_lists = content_lists[:args.limit]

    doc_processor = _build_doc_processor()
    if not doc_processor.vector_store:
        raise SystemExit("Vector store is not configured")
    image_vlm = getattr(getattr(doc_processor, "image_proc", None), "vlm", None)
    if {"image", "chart", "equation"} & target_types and not (image_vlm and image_vlm.configured):
        raise SystemExit("VLM is not configured for image/chart/equation backfill")
    if args.clear:
        doc_processor.vector_store.clear()
        print("Chroma collection cleared.", flush=True)

    pdf_map = build_source_pdf_map()
    start_time = time.time()
    type_stats = Counter()
    totals = Counter()

    print(
        json.dumps(
            {
                "documents": len(content_lists),
                "target_types": sorted(target_types),
                "vlm_mode": args.vlm_mode,
                "vlm_enabled": bool(image_vlm and image_vlm.configured),
                "vlm_model": getattr(image_vlm, "model_name", "") or os.getenv("QWEN_VL_MODEL", ""),
                "graph_llm": args.graph_llm,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )

    for doc_idx, (stem, cl_path) in enumerate(content_lists, 1):
        try:
            data = json.loads(cl_path.read_text(encoding="utf-8"))
        except Exception as exc:
            totals["errors"] += 1
            print(f"[error] {stem}: failed to read {cl_path}: {exc}", flush=True)
            continue

        for item in data:
            type_stats[item.get("type", "unknown")] += 1

        result = asyncio.run(
            process_multimodal_doc(
                stem,
                cl_path,
                data=data,
                pdf_map=pdf_map,
                doc_processor=doc_processor,
                target_types=target_types,
                graph_llm=args.graph_llm,
            )
        )
        totals.update(result)
        totals["documents"] += 1

        elapsed = time.time() - start_time
        print(
            f"[doc {doc_idx}/{len(content_lists)}] {stem} "
            f"processed={result['processed']} inserted={result['inserted']} "
            f"existing={result['existing']} missing_assets={result['missing_assets']} "
            f"errors={len(result['errors'])} elapsed={elapsed:.0f}s",
            flush=True,
        )

        if result["errors"]:
            print(f"[warn] {stem}: {len(result['errors'])} multimodal items failed", flush=True)

        if doc_idx % 25 == 0:
            print(
                f"[{doc_idx}/{len(content_lists)}] inserted={totals['inserted']} "
                f"existing={totals['existing']} missing_assets={totals['missing_assets']} "
                f"errors={totals['errors']} elapsed={elapsed:.0f}s",
                flush=True,
            )

    elapsed = time.time() - start_time
    vector_count = doc_processor.vector_store.count()

    print("\n=== Multimodal Backfill Complete ===", flush=True)
    print(f"Documents processed: {totals['documents']}", flush=True)
    print(f"Items processed:     {totals['processed']}", flush=True)
    print(f"Inserted vectors:    {totals['inserted']}", flush=True)
    print(f"Existing vectors:    {totals['existing']}", flush=True)
    print(f"Missing assets:      {totals['missing_assets']}", flush=True)
    print(f"Graph entities:      {totals['entities']}", flush=True)
    print(f"Graph relations:     {totals['relations']}", flush=True)
    print(f"Errors:              {totals['errors']}", flush=True)
    print(f"Vector count:        {vector_count}", flush=True)
    print(f"Time:                {elapsed:.0f}s ({elapsed/60:.1f}min)", flush=True)
    print(f"Parsed block stats:  {dict(type_stats)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
