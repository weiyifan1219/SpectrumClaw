#!/usr/bin/env python3
"""Batch MinerU parse — one file at a time, immediate output, resumable.

Each PDF is processed independently. Output goes to data/parsed/<stem>/auto/
with content_list.json, images/, .md etc. Already-completed files are skipped.

Supports dual-GPU via --shards/--shard-index or CUDA_VISIBLE_DEVICES.

Usage:
    # GPU 0 (first half)
    CUDA_VISIBLE_DEVICES=0 MINERU_MODEL_SOURCE=local python scripts/batch_mineru_parse.py --shards 2 --shard-index 0

    # GPU 1 (second half)
    CUDA_VISIBLE_DEVICES=1 MINERU_MODEL_SOURCE=local python scripts/batch_mineru_parse.py --shards 2 --shard-index 1
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PDF_DIR = PROJECT_ROOT / "data" / "knowledge_base" / "raw"
OUTPUT_DIR = PROJECT_ROOT / "data" / "parsed"


def is_done(pdf_path: Path) -> bool:
    stem = pdf_path.stem
    out_dir = OUTPUT_DIR / stem
    content_list = list(out_dir.rglob("*content_list.json"))
    return len(content_list) > 0


def parse_one(pdf_path: Path, backend: str = "pipeline") -> dict:
    stem = pdf_path.stem
    out_dir = OUTPUT_DIR / stem
    out_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env.setdefault("MINERU_MODEL_SOURCE", "local")

    cmd = [
        sys.executable, "-m", "mineru.cli.client",
        "-p", str(pdf_path),
        "-o", str(out_dir),
        "-b", backend,
        "-m", "auto",
    ]

    start = time.time()
    result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=1800)
    elapsed = time.time() - start

    content_list = list(out_dir.rglob("*content_list.json"))
    success = len(content_list) > 0

    return {
        "file": pdf_path.name,
        "success": success,
        "seconds": round(elapsed, 1),
        "returncode": result.returncode,
        "error": result.stderr[-500:] if not success and result.stderr else "",
    }


def main():
    ap = argparse.ArgumentParser(description="Batch MinerU parse, one file at a time")
    ap.add_argument("--dir", type=str, help="PDF directory")
    ap.add_argument("--shards", type=int, default=1)
    ap.add_argument("--shard-index", type=int, default=0)
    ap.add_argument("--backend", type=str, default="pipeline")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    pdf_dir = Path(args.dir) if args.dir else PDF_DIR
    all_pdfs = sorted(pdf_dir.glob("*.pdf"))

    # Shard
    pdfs = [p for i, p in enumerate(all_pdfs) if i % args.shards == args.shard_index]
    if args.limit:
        pdfs = pdfs[:args.limit]

    # Skip already done
    todo = [p for p in pdfs if not is_done(p)]
    print(f"[shard {args.shard_index}/{args.shards}] Total: {len(pdfs)}, Done: {len(pdfs)-len(todo)}, Todo: {len(todo)}", flush=True)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    failed = []

    for i, pdf in enumerate(todo, 1):
        print(f"[{i}/{len(todo)}] {pdf.name} ...", end=" ", flush=True)
        try:
            r = parse_one(pdf, backend=args.backend)
            if r["success"]:
                print(f"OK ({r['seconds']}s)", flush=True)
            else:
                print(f"FAILED ({r['seconds']}s): {r['error'][:100]}", flush=True)
                failed.append(r)
        except subprocess.TimeoutExpired:
            print("TIMEOUT (1800s)", flush=True)
            failed.append({"file": pdf.name, "success": False, "error": "timeout"})
        except Exception as e:
            print(f"ERROR: {e}", flush=True)
            failed.append({"file": pdf.name, "success": False, "error": str(e)})

    print(f"\nDone: {len(todo) - len(failed)} succeeded, {len(failed)} failed", flush=True)
    if failed:
        fail_path = PROJECT_ROOT / "logs" / f"mineru_failed_shard{args.shard_index}.json"
        fail_path.write_text(json.dumps(failed, indent=2, ensure_ascii=False))
        print(f"Failed files saved to: {fail_path}", flush=True)


if __name__ == "__main__":
    main()
