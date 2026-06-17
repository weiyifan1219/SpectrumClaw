#!/usr/bin/env python3
"""Batch MinerU parse with persistent API server — model loads once.

Starts a MinerU FastAPI server (model stays in GPU memory), then submits
PDFs one by one. Each file's output is written immediately to data/parsed/<stem>/.
Supports resume (skips files that already have content_list.json).

Usage:
    CUDA_VISIBLE_DEVICES=1 MINERU_MODEL_SOURCE=local python scripts/batch_mineru_parse_api.py --shards 2 --shard-index 1 --port 39502
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PDF_DIR = PROJECT_ROOT / "data" / "knowledge_base" / "raw"
OUTPUT_DIR = PROJECT_ROOT / "data" / "parsed"


def is_done(pdf_path: Path) -> bool:
    stem = pdf_path.stem
    out_dir = OUTPUT_DIR / stem
    return len(list(out_dir.rglob("*content_list.json"))) > 0


def wait_for_server(port: int, timeout: int = 120):
    url = f"http://127.0.0.1:{port}/docs"
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = httpx.get(url, timeout=5)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(2)
    return False


def submit_and_wait(pdf_path: Path, port: int, backend: str = "pipeline") -> dict:
    """Submit a single PDF to the API and wait for result."""
    url = f"http://127.0.0.1:{port}"
    start = time.time()

    # Upload file
    with open(pdf_path, "rb") as f:
        files = {"file": (pdf_path.name, f, "application/pdf")}
        params = {"backend": backend, "parse_method": "auto"}
        r = httpx.post(f"{url}/parse", files=files, params=params, timeout=60)

    if r.status_code != 200:
        return {"success": False, "error": f"Upload failed: {r.status_code} {r.text[:200]}"}

    task_info = r.json()
    task_id = task_info.get("task_id")
    if not task_id:
        return {"success": False, "error": f"No task_id: {task_info}"}

    # Poll for completion
    while True:
        time.sleep(3)
        try:
            r = httpx.get(f"{url}/tasks/{task_id}", timeout=10)
            status = r.json().get("status")
            if status == "completed":
                break
            elif status == "failed":
                error = r.json().get("error", "unknown")
                return {"success": False, "error": error[:200], "seconds": round(time.time() - start, 1)}
        except Exception as e:
            if time.time() - start > 1800:
                return {"success": False, "error": "timeout polling", "seconds": 1800}

    # Download result
    r = httpx.get(f"{url}/tasks/{task_id}/result", timeout=120)
    if r.status_code != 200:
        return {"success": False, "error": f"Result download failed: {r.status_code}"}

    # Save result to output dir
    stem = pdf_path.stem
    out_dir = OUTPUT_DIR / stem
    out_dir.mkdir(parents=True, exist_ok=True)

    # Result is a zip or directory structure from the API
    result_data = r.json() if r.headers.get("content-type", "").startswith("application/json") else None

    elapsed = round(time.time() - start, 1)
    # Check if output was written
    if is_done(pdf_path):
        return {"success": True, "seconds": elapsed}
    else:
        return {"success": False, "error": "No content_list after download", "seconds": elapsed}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shards", type=int, default=1)
    ap.add_argument("--shard-index", type=int, default=0)
    ap.add_argument("--port", type=int, default=39502)
    ap.add_argument("--backend", type=str, default="pipeline")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    pdf_dir = PDF_DIR
    all_pdfs = sorted(pdf_dir.glob("*.pdf"))
    pdfs = [p for i, p in enumerate(all_pdfs) if i % args.shards == args.shard_index]
    if args.limit:
        pdfs = pdfs[:args.limit]

    todo = [p for p in pdfs if not is_done(p)]
    print(f"[shard {args.shard_index}/{args.shards}] Total: {len(pdfs)}, Done: {len(pdfs)-len(todo)}, Todo: {len(todo)}", flush=True)

    if not todo:
        print("Nothing to do!", flush=True)
        return

    # Start MinerU API server
    env = os.environ.copy()
    env.setdefault("MINERU_MODEL_SOURCE", "local")
    server_proc = subprocess.Popen(
        [sys.executable, "-m", "mineru.cli.fast_api", "--host", "127.0.0.1", "--port", str(args.port)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    print(f"Starting MinerU API server on port {args.port}...", flush=True)

    if not wait_for_server(args.port):
        print("ERROR: Server failed to start!", flush=True)
        server_proc.kill()
        return

    print(f"Server ready on port {args.port}", flush=True)

    # Process files one by one using mineru CLI with --api-url
    failed = []
    for i, pdf in enumerate(todo, 1):
        print(f"[{i}/{len(todo)}] {pdf.name} ...", end=" ", flush=True)
        stem = pdf.stem
        out_dir = OUTPUT_DIR / stem
        out_dir.mkdir(parents=True, exist_ok=True)

        try:
            cmd = [
                sys.executable, "-m", "mineru.cli.client",
                "-p", str(pdf),
                "-o", str(out_dir),
                "-b", args.backend,
                "-m", "auto",
                "--api-url", f"http://127.0.0.1:{args.port}",
            ]
            result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=1800)
            if is_done(pdf):
                # Get approximate time from output
                print(f"OK", flush=True)
            else:
                err = result.stderr[-200:] if result.stderr else "no output"
                print(f"FAILED: {err}", flush=True)
                failed.append({"file": pdf.name, "error": err})
        except subprocess.TimeoutExpired:
            print("TIMEOUT", flush=True)
            failed.append({"file": pdf.name, "error": "timeout"})
        except Exception as e:
            print(f"ERROR: {e}", flush=True)
            failed.append({"file": pdf.name, "error": str(e)})

    server_proc.terminate()
    server_proc.wait(timeout=10)

    print(f"\nDone: {len(todo) - len(failed)} succeeded, {len(failed)} failed", flush=True)
    if failed:
        fail_path = PROJECT_ROOT / "logs" / f"mineru_failed_shard{args.shard_index}.json"
        fail_path.write_text(json.dumps(failed, indent=2, ensure_ascii=False))
        print(f"Failed files saved to: {fail_path}", flush=True)


if __name__ == "__main__":
    main()
