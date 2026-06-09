"""Parallel-friendly MinerU preparse worker.

This module only runs MinerU and stores content_list cache files. It does not
write Chroma, graph JSON, or the document registry, so multiple worker
processes can run safely on disjoint shards.
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

from backend.rag.parsers.mineru_parser import MinerUParser


def _resolve_pdf_paths(directory: str | None, file_path: str | None) -> list[str]:
    if file_path:
        return [str(Path(file_path))]

    root = Path(directory) if directory else PROJECT_ROOT / "data" / "knowledge_base" / "raw"
    return sorted(str(p) for p in root.glob("*.pdf"))


def _shard(paths: list[str], shards: int, shard_index: int) -> list[str]:
    if shards <= 0:
        raise ValueError("--shards must be >= 1")
    if shard_index < 0 or shard_index >= shards:
        raise ValueError("--shard-index must be in [0, shards)")
    return [p for i, p in enumerate(paths) if i % shards == shard_index]


def _emit(event: dict) -> None:
    print(json.dumps(event, ensure_ascii=False), flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="Preparse PDFs with MinerU into cache")
    ap.add_argument("--dir", type=str, help="Directory containing PDFs")
    ap.add_argument("--file", type=str, help="Single PDF to preparse")
    ap.add_argument("--limit", type=int, help="Limit selected files after sharding")
    ap.add_argument("--shards", type=int, default=1, help="Total shard count")
    ap.add_argument("--shard-index", type=int, default=0, help="This worker shard index")
    ap.add_argument("--force", action="store_true", help="Refresh cache even if valid")
    args = ap.parse_args()

    if args.force:
        os.environ["MINERU_CACHE_REFRESH"] = "1"

    all_paths = _resolve_pdf_paths(args.dir, args.file)
    paths = _shard(all_paths, args.shards, args.shard_index)
    if args.limit:
        paths = paths[:args.limit]

    parser = MinerUParser()
    started = time.time()
    summary = {"selected": len(paths), "cached": 0, "parsed": 0, "failed": 0}

    _emit({
        "event": "worker_start",
        "worker": args.shard_index,
        "shards": args.shards,
        "selected": len(paths),
        "total": len(all_paths),
        "cuda_visible_devices": os.getenv("CUDA_VISIBLE_DEVICES", ""),
        "cache_dir": os.getenv("MINERU_CACHE_DIR", str(PROJECT_ROOT / "data" / "mineru_cache")),
    })

    for offset, path in enumerate(paths, start=1):
        filename = Path(path).name
        if not args.force and parser.is_cached(path):
            summary["cached"] += 1
            _emit({
                "event": "file_cached",
                "worker": args.shard_index,
                "offset": offset,
                "selected": len(paths),
                "file": filename,
            })
            continue

        file_started = time.time()
        try:
            doc = parser.parse(path)
            elapsed = round(time.time() - file_started, 2)
            summary["parsed"] += 1
            _emit({
                "event": "file_parsed",
                "worker": args.shard_index,
                "offset": offset,
                "selected": len(paths),
                "file": filename,
                "blocks": len(doc.blocks),
                "seconds": elapsed,
            })
        except Exception as exc:
            elapsed = round(time.time() - file_started, 2)
            summary["failed"] += 1
            _emit({
                "event": "file_failed",
                "worker": args.shard_index,
                "offset": offset,
                "selected": len(paths),
                "file": filename,
                "seconds": elapsed,
                "error": str(exc)[:1000],
            })

    summary["seconds"] = round(time.time() - started, 2)
    _emit({"event": "worker_complete", "worker": args.shard_index, **summary})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
