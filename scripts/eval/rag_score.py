"""RAG Scoring — compute retrieval and answer metrics from raw predictions.

Usage:
    python -m scripts.eval.rag_score \
        --run-dir runs/rag_eval_official \
        --gold data/eval/rag_gold.jsonl

    # With human judgements:
    python -m scripts.eval.rag_score \
        --run-dir runs/rag_eval_official \
        --gold data/eval/rag_gold.jsonl \
        --human runs/rag_eval_official/human_judgement_template.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path


# ─── Metric functions ───


def recall_at_k(retrieved_ids: list[str], gold_ids: list[str], k: int) -> float:
    """Whether any gold_id appears in top-k retrieved."""
    if not gold_ids:
        return 0.0
    top_k = set(retrieved_ids[:k])
    return 1.0 if any(g in top_k for g in gold_ids) else 0.0


def precision_at_k(retrieved_ids: list[str], gold_ids: list[str], k: int) -> float:
    """Fraction of top-k that are relevant."""
    if not gold_ids or k == 0:
        return 0.0
    top_k = retrieved_ids[:k]
    hits = sum(1 for r in top_k if r in gold_ids)
    return hits / min(k, len(top_k)) if top_k else 0.0


def mrr_at_k(retrieved_ids: list[str], gold_ids: list[str], k: int) -> float:
    """Reciprocal rank of the first relevant item in top-k."""
    if not gold_ids:
        return 0.0
    gold_set = set(gold_ids)
    for i, rid in enumerate(retrieved_ids[:k]):
        if rid in gold_set:
            return 1.0 / (i + 1)
    return 0.0


def source_hit_at_k(retrieved_sources: list[str], gold_patterns: list[str], k: int) -> float:
    """Whether any gold source pattern matches a top-k source path."""
    if not gold_patterns:
        return 0.0
    top_k = retrieved_sources[:k]
    for src in top_k:
        for pat in gold_patterns:
            if re.search(pat, src, re.IGNORECASE):
                return 1.0
    return 0.0


def keyword_coverage(answer: str, expected_keywords: list[str]) -> float:
    """Fraction of expected keywords found in the answer (case-insensitive)."""
    if not expected_keywords:
        return 0.0
    lower = answer.lower()
    hits = sum(1 for kw in expected_keywords if kw.lower() in lower)
    return hits / len(expected_keywords)


def citation_accuracy(citations: list[dict], gold_doc_ids: list[str], gold_patterns: list[str]) -> float:
    """Fraction of citations matching gold docs or source patterns."""
    if not citations:
        return 0.0
    correct = 0
    for c in citations:
        cid = c.get("doc_id", "")
        src = c.get("source_path", c.get("source", ""))
        if cid in gold_doc_ids:
            correct += 1
            continue
        for pat in gold_patterns:
            if re.search(pat, src, re.IGNORECASE) or re.search(pat, cid, re.IGNORECASE):
                correct += 1
                break
    return correct / len(citations)


def compute_final_score(
    recall_5: float,
    mrr_10: float,
    kw_cov: float,
    cite_acc: float,
    answer_acc: float | None,
) -> float:
    """Weighted composite score."""
    norm_aa = (answer_acc / 2.0) if answer_acc is not None else 0.5
    return (
        0.35 * recall_5
        + 0.20 * mrr_10
        + 0.20 * kw_cov
        + 0.15 * cite_acc
        + 0.10 * norm_aa
    )


# ─── Scoring pipeline ───


def score_predictions(
    predictions: list[dict],
    questions: list[dict],
    gold: list[dict] | None,
    human: dict[str, dict] | None = None,
) -> list[dict]:
    """Score all predictions. Returns per-question-method metrics."""
    q_map = {q["id"]: q for q in questions}
    g_map = {g["id"]: g for g in gold} if gold else {}

    rows = []
    for pred in predictions:
        qid = pred["question_id"]
        method = pred["method"]
        q = q_map.get(qid, {})
        g = g_map.get(qid, {})

        retrieved_ids = [b.get("block_id", "") for b in pred.get("retrieved_blocks", [])]
        retrieved_sources = [b.get("source_path", "") for b in pred.get("retrieved_blocks", [])]
        # Also include citation sources for source_hit (some methods return
        # citations but not raw blocks in the same structure).
        citation_sources = [
            c.get("source_path", c.get("source", ""))
            for c in pred.get("citations", [])
        ]
        all_sources = [s for s in (retrieved_sources + citation_sources) if s]

        gold_block_ids = g.get("gold_block_ids", [])
        gold_doc_ids = g.get("gold_doc_ids", [])
        gold_src_patterns = g.get("gold_source_patterns", q.get("expected_source_patterns", []))
        exp_keywords = g.get("expected_keywords", q.get("expected_keywords", []))

        r3 = recall_at_k(retrieved_ids, gold_block_ids, 3) if gold_block_ids else None
        r5 = recall_at_k(retrieved_ids, gold_block_ids, 5) if gold_block_ids else None
        r10 = recall_at_k(retrieved_ids, gold_block_ids, 10) if gold_block_ids else None
        p5 = precision_at_k(retrieved_ids, gold_block_ids, 5) if gold_block_ids else None
        m10 = mrr_at_k(retrieved_ids, gold_block_ids, 10) if gold_block_ids else None
        sh5 = source_hit_at_k(all_sources, gold_src_patterns, 5)

        answer = pred.get("answer", "")
        kw_cov = keyword_coverage(answer, exp_keywords)
        cite_ct = len(pred.get("citations", []))
        cite_acc = citation_accuracy(pred.get("citations", []), gold_doc_ids, gold_src_patterns)

        # Human judgements
        hkey = f"{qid}_{method}"
        h = human.get(hkey, {}) if human else {}
        answer_acc = h.get("answer_accuracy")
        hall_flag = h.get("hallucination_flag")

        final = compute_final_score(
            r5 if r5 is not None else sh5,
            m10 if m10 is not None else 0.0,
            kw_cov,
            cite_acc,
            answer_acc,
        )

        rows.append({
            "question_id": qid,
            "category": q.get("category", ""),
            "method": method,
            "recall_at_3": r3,
            "recall_at_5": r5,
            "recall_at_10": r10,
            "precision_at_5": p5,
            "mrr_at_10": m10,
            "source_hit_at_5": sh5,
            "keyword_coverage": round(kw_cov, 4),
            "citation_count": cite_ct,
            "citation_accuracy": round(cite_acc, 4),
            "answer_accuracy": answer_acc,
            "hallucination_flag": hall_flag,
            "final_score": round(final, 4),
            "latency_ms": pred.get("latency_ms", 0),
        })

    return rows


def summarize_metrics(per_question: list[dict]) -> list[dict]:
    """Aggregate per-question metrics into per-method summary."""
    from collections import defaultdict

    by_method: dict[str, list[dict]] = defaultdict(list)
    for row in per_question:
        by_method[row["method"]].append(row)

    summaries = []
    for method, rows in by_method.items():
        n = len(rows)

        def avg(key):
            vals = [r[key] for r in rows if r[key] is not None]
            return round(sum(vals) / len(vals), 4) if vals else None

        summaries.append({
            "method": method,
            "mean_recall_at_3": avg("recall_at_3"),
            "mean_recall_at_5": avg("recall_at_5"),
            "mean_recall_at_10": avg("recall_at_10"),
            "mean_precision_at_5": avg("precision_at_5"),
            "mean_mrr_at_10": avg("mrr_at_10"),
            "mean_source_hit_at_5": avg("source_hit_at_5"),
            "mean_keyword_coverage": avg("keyword_coverage"),
            "mean_citation_accuracy": avg("citation_accuracy"),
            "mean_answer_accuracy": avg("answer_accuracy"),
            "hallucination_rate": round(
                sum(1 for r in rows if r.get("hallucination_flag") == 1) / n, 4
            ) if any(r.get("hallucination_flag") is not None for r in rows) else None,
            "mean_final_score": avg("final_score"),
            "mean_latency_ms": avg("latency_ms"),
        })

    return summaries


def save_results(per_question: list[dict], summary: list[dict], out_dir: Path):
    """Save metrics CSVs and JSON."""
    # Per-question CSV
    csv_path = out_dir / "metrics_per_question.csv"
    if per_question:
        with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(per_question[0].keys()))
            writer.writeheader()
            writer.writerows(per_question)
        print(f"Saved {csv_path}")

    # Summary CSV
    sum_csv = out_dir / "metrics_summary.csv"
    if summary:
        with open(sum_csv, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(summary[0].keys()))
            writer.writeheader()
            writer.writerows(summary)
        print(f"Saved {sum_csv}")

    # Summary JSON
    sum_json = out_dir / "metrics_summary.json"
    sum_json.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved {sum_json}")

    # Human judgement template
    tmpl_path = out_dir / "human_judgement_template.csv"
    if not tmpl_path.exists():
        with open(tmpl_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["question_id", "method", "answer_accuracy", "hallucination_flag", "notes"])
            for row in per_question:
                writer.writerow([row["question_id"], row["method"], "", "", ""])
        print(f"Saved {tmpl_path}")


def load_human_judgements(path: Path) -> dict[str, dict]:
    """Load human judgement CSV into {qid_method: {answer_accuracy, hallucination_flag}}."""
    result = {}
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = f"{row['question_id']}_{row['method']}"
            aa = row.get("answer_accuracy", "").strip()
            hf = row.get("hallucination_flag", "").strip()
            result[key] = {
                "answer_accuracy": int(aa) if aa else None,
                "hallucination_flag": int(hf) if hf else None,
            }
    return result


# ─── CLI ───


def main():
    parser = argparse.ArgumentParser(description="Score RAG eval predictions")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--gold", default=None)
    parser.add_argument("--human", default=None)
    parser.add_argument("--questions", default="data/eval/rag_questions.jsonl")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)

    # Load predictions
    pred_path = run_dir / "raw_predictions.jsonl"
    predictions = []
    for line in pred_path.read_text(encoding="utf-8").strip().splitlines():
        if line.strip():
            predictions.append(json.loads(line))

    # Load questions
    questions = []
    qpath = Path(args.questions)
    if qpath.suffix == ".jsonl":
        for line in qpath.read_text(encoding="utf-8").strip().splitlines():
            if line.strip():
                questions.append(json.loads(line))
    else:
        questions = json.loads(qpath.read_text(encoding="utf-8"))

    # Load gold (optional)
    gold = None
    gold_path = Path(args.gold) if args.gold else run_dir / "rag_gold.jsonl"
    if gold_path.exists():
        gold = []
        for line in gold_path.read_text(encoding="utf-8").strip().splitlines():
            if line.strip():
                gold.append(json.loads(line))
        print(f"Loaded {len(gold)} gold entries from {gold_path}")

    # Load human judgements (optional)
    human = None
    human_path = Path(args.human) if args.human else run_dir / "human_judgement_template.csv"
    if human_path.exists():
        human = load_human_judgements(human_path)
        filled = sum(1 for v in human.values() if v.get("answer_accuracy") is not None)
        print(f"Loaded human judgements: {filled}/{len(human)} filled")

    # Score
    per_question = score_predictions(predictions, questions, gold, human)
    summary = summarize_metrics(per_question)

    # Save
    save_results(per_question, summary, run_dir)

    # Print summary table
    print("\n" + "=" * 70)
    print("METRICS SUMMARY")
    print("=" * 70)
    for s in summary:
        print(f"\n  Method: {s['method']}")
        for k, v in s.items():
            if k == "method":
                continue
            if v is not None:
                print(f"    {k}: {v}")


if __name__ == "__main__":
    main()
