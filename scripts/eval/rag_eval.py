"""RAG Evaluation — run llm_only / vector_rag / spectrumclaw_rag on question set.

Usage:
    python -m scripts.eval.rag_eval \
        --questions data/eval/rag_questions.jsonl \
        --methods llm_only,vector_rag,spectrumclaw_rag \
        --top-k 10 \
        --out runs/rag_eval_official

    python -m scripts.eval.rag_eval \
        --questions data/eval/rag_questions.jsonl \
        --methods spectrumclaw_rag \
        --top-k 20 \
        --mode collect_candidates \
        --out runs/rag_eval_candidates
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

BASE_URL = os.environ.get("SPECTRUMCLAW_API_BASE", "http://127.0.0.1:8230")
TIMEOUT = 180.0


# ─── Method implementations ───


async def run_llm_only(query: str, client: httpx.AsyncClient, top_k: int = 10, **kw) -> dict[str, Any]:
    """Direct LLM call without any retrieval context — via /api/eval/llm_only."""
    t0 = time.time()
    try:
        resp = await client.post(
            f"{BASE_URL}/api/eval/llm_only",
            json={"question": query},
            timeout=TIMEOUT,
        )
        latency = int((time.time() - t0) * 1000)
        if resp.status_code != 200:
            return {"answer": "", "citations": [], "retrieved_blocks": [],
                    "latency_ms": latency, "token_usage": {},
                    "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
        data = resp.json()
        return {
            "answer": data.get("answer", ""),
            "citations": data.get("citations", []),
            "retrieved_blocks": data.get("retrieved_blocks", []),
            "latency_ms": latency,
            "token_usage": data.get("token_usage", {}),
            "error": None,
        }
    except Exception as e:
        return {"answer": "", "citations": [], "retrieved_blocks": [],
                "latency_ms": int((time.time() - t0) * 1000), "token_usage": {},
                "error": str(e)}


async def run_vector_rag(query: str, client: httpx.AsyncClient, top_k: int = 10, **kw) -> dict[str, Any]:
    """Vector-only retrieval + LLM generation — via /api/eval/vector_rag."""
    t0 = time.time()
    try:
        resp = await client.post(
            f"{BASE_URL}/api/eval/vector_rag",
            json={"question": query, "top_k": top_k},
            timeout=TIMEOUT,
        )
        latency = int((time.time() - t0) * 1000)
        if resp.status_code != 200:
            return {"answer": "", "citations": [], "retrieved_blocks": [],
                    "latency_ms": latency, "token_usage": {},
                    "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
        data = resp.json()
        return {
            "answer": data.get("answer", ""),
            "citations": data.get("citations", []),
            "retrieved_blocks": data.get("retrieved_blocks", []),
            "latency_ms": latency,
            "token_usage": data.get("token_usage", {}),
            "error": None,
        }
    except Exception as e:
        return {"answer": "", "citations": [], "retrieved_blocks": [],
                "latency_ms": int((time.time() - t0) * 1000), "token_usage": {},
                "error": str(e)}


async def run_spectrumclaw_rag(query: str, client: httpx.AsyncClient, top_k: int = 10, **kw) -> dict[str, Any]:
    """Full SpectrumClaw RAG via the /api/rag/query endpoint."""
    t0 = time.time()
    try:
        resp = await client.post(
            f"{BASE_URL}/api/rag/query",
            json={"question": query},
            timeout=TIMEOUT,
        )
        latency = int((time.time() - t0) * 1000)
        if resp.status_code != 200:
            return {
                "answer": "",
                "citations": [],
                "retrieved_blocks": [],
                "latency_ms": latency,
                "token_usage": {},
                "error": f"HTTP {resp.status_code}: {resp.text[:200]}",
            }

        data = resp.json()
        answer = data.get("answer", "")
        citations = data.get("citations", [])
        debug = data.get("debug", {})

        # The full RAG pipeline returns evidence in `citations` (with source,
        # page, block_id, relevance). `debug.retrieved_blocks` is often empty
        # because the workflow packs context internally. Build retrieved list
        # from citations which carry the actual retrieval evidence.
        retrieved = []
        for i, c in enumerate(citations[:top_k]):
            retrieved.append({
                "rank": i + 1,
                "block_id": c.get("block_id", c.get("id", "")),
                "doc_id": c.get("doc_id", ""),
                "source_path": c.get("source", c.get("source_path", "")),
                "page_idx": c.get("page", c.get("page_idx", 0)),
                "block_type": c.get("block_type", "text"),
                "score": round(float(c.get("relevance", c.get("score", 0))), 4),
                "rerank_score": round(float(c.get("rerank_score", 0)), 4) if c.get("rerank_score") else None,
                "content_snippet": c.get("text", c.get("content", c.get("snippet", ""))),
            })

        return {
            "answer": answer,
            "citations": citations,
            "retrieved_blocks": retrieved,
            "latency_ms": latency,
            "token_usage": {},
            "error": None,
        }
    except Exception as e:
        return {
            "answer": "",
            "citations": [],
            "retrieved_blocks": [],
            "latency_ms": int((time.time() - t0) * 1000),
            "token_usage": {},
            "error": str(e),
        }


METHOD_FN = {
    "llm_only": run_llm_only,
    "vector_rag": run_vector_rag,
    "spectrumclaw_rag": run_spectrumclaw_rag,
}


# ─── Main eval runner ───


async def run_eval(
    questions: list[dict],
    methods: list[str],
    top_k: int,
    out_dir: Path,
    mode: str = "full",
):
    out_dir.mkdir(parents=True, exist_ok=True)

    config = {
        "generated_at": datetime.now().isoformat(),
        "questions_file": "data/eval/rag_questions.jsonl",
        "methods": methods,
        "top_k": top_k,
        "mode": mode,
        "num_questions": len(questions),
        "base_url": BASE_URL,
    }
    (out_dir / "config.json").write_text(json.dumps(config, indent=2, ensure_ascii=False))

    predictions = []

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        for qi, q in enumerate(questions):
            qid = q["id"]
            query = q["query"]
            print(f"[{qi+1}/{len(questions)}] {qid}: {query[:40]}...")

            for method in methods:
                fn = METHOD_FN.get(method)
                if not fn:
                    print(f"  SKIP unknown method: {method}")
                    continue

                print(f"  → {method}...", end=" ", flush=True)
                result = await fn(query, client, top_k=top_k)
                print(f"{'OK' if not result['error'] else 'ERR: ' + str(result['error'])[:50]} ({result['latency_ms']}ms)")

                pred = {
                    "question_id": qid,
                    "method": method,
                    "query": query,
                    "answer": result["answer"],
                    "citations": result["citations"],
                    "retrieved_blocks": result["retrieved_blocks"],
                    "latency_ms": result["latency_ms"],
                    "token_usage": result["token_usage"],
                    "error": result["error"],
                }
                predictions.append(pred)

    # Save raw predictions
    pred_path = out_dir / "raw_predictions.jsonl"
    with open(pred_path, "w", encoding="utf-8") as f:
        for p in predictions:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    print(f"\nSaved {len(predictions)} predictions → {pred_path}")

    # If collect_candidates mode, generate CSV for human annotation
    if mode == "collect_candidates":
        _save_candidate_csv(predictions, out_dir)

    return predictions


def _save_candidate_csv(predictions: list[dict], out_dir: Path):
    """Save candidate evidence CSV for human annotation."""
    import csv

    csv_path = out_dir / "candidate_evidence.csv"
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "question_id", "rank", "block_id", "doc_id", "source_path",
            "page_idx", "block_type", "score", "rerank_score",
            "content_snippet", "is_relevant",
        ])
        for pred in predictions:
            for b in pred.get("retrieved_blocks", []):
                writer.writerow([
                    pred["question_id"],
                    b["rank"],
                    b["block_id"],
                    b["doc_id"],
                    b["source_path"],
                    b["page_idx"],
                    b["block_type"],
                    b["score"],
                    b["rerank_score"] or "",
                    b["content_snippet"][:150],
                    "",  # is_relevant — to be filled by human
                ])
    print(f"Saved candidate evidence → {csv_path}")


# ─── CLI ───


def main():
    parser = argparse.ArgumentParser(description="SpectrumClaw RAG Evaluation")
    parser.add_argument("--questions", default="data/eval/rag_questions.jsonl")
    parser.add_argument("--methods", default="llm_only,vector_rag,spectrumclaw_rag")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--mode", choices=["full", "collect_candidates"], default="full")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    # Load questions
    questions = []
    qpath = Path(args.questions)
    if qpath.suffix == ".jsonl":
        for line in qpath.read_text(encoding="utf-8").strip().splitlines():
            if line.strip():
                questions.append(json.loads(line))
    else:
        questions = json.loads(qpath.read_text(encoding="utf-8"))

    methods = [m.strip() for m in args.methods.split(",")]

    if args.out:
        out_dir = Path(args.out)
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = Path(f"runs/rag_eval_{ts}")

    print(f"RAG Eval: {len(questions)} questions × {len(methods)} methods → {out_dir}")
    asyncio.run(run_eval(questions, methods, args.top_k, out_dir, args.mode))


if __name__ == "__main__":
    main()
