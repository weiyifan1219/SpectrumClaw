"""RAG Scoring — QA Accuracy evaluation with LLM judge.

Replaces block-level Recall/MRR/Precision with end-to-end QA accuracy scoring.
Uses an LLM judge to compare answers against reference answers on a 0~1 scale.

Usage:
    python -m scripts.eval.rag_score \
        --run-dir runs/rag_eval_test \
        --questions data/eval/rag_questions.jsonl

    # Skip judge (use only automatic metrics):
    python -m scripts.eval.rag_score \
        --run-dir runs/rag_eval_test \
        --questions data/eval/rag_questions.jsonl \
        --no-judge
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import re
import time
from pathlib import Path

import httpx

BASE_URL = os.environ.get("SPECTRUMCLAW_API_BASE", "http://127.0.0.1:8230")
TIMEOUT = 120.0


# ─── Automatic metric functions ───


def source_hit_at_k(sources: list[str], gold_patterns: list[str], k: int) -> float:
    """Whether any gold source pattern matches a top-k source path."""
    if not gold_patterns:
        return 0.0
    top_k = sources[:k]
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


def citation_accuracy(citations: list[dict], gold_patterns: list[str]) -> float:
    """Fraction of citations matching gold source patterns."""
    if not citations:
        return 0.0
    correct = 0
    for c in citations:
        src = c.get("source_path", c.get("source", ""))
        for pat in gold_patterns:
            if re.search(pat, src, re.IGNORECASE):
                correct += 1
                break
    return correct / len(citations)


# ─── LLM Judge ───

JUDGE_PROMPT = """你是一个频谱领域专家评审。请对比参考答案和待评答案，从以下维度打分（0~1 连续值，精确到小数点后两位）。

## 评分维度

1. **answer_accuracy** (0~1): 回答的正确性和完整性
   - 0.0: 完全错误、答非所问、输出了工具调用代码而非实际回答、或声称"信息不足"而未给出任何有效信息
   - 0.3: 回答了但大部分内容不正确或严重不完整
   - 0.5: 部分正确,但缺少关键信息
   - 0.7: 基本正确,覆盖了主要知识点但有遗漏
   - 0.9: 正确且完整,覆盖了参考答案的核心要点
   - 1.0: 完美回答,甚至超出参考答案的深度

2. **hallucination_score** (0~1): 幻觉程度（0=无幻觉,1=严重幻觉）
   - 0.0: 所有陈述都有可靠依据,或明确标注了不确定性,未编造任何事实
   - 0.2: 有轻微推测但不影响结论
   - 0.4: 有部分无依据的具体陈述（如引用了未在上下文中出现的文献号）
   - 0.6: 多处编造具体事实（如杜撰 ITU-R 建议书编号、编造具体频率数据）
   - 0.8: 大量编造且看起来很权威,容易误导读者
   - 1.0: 几乎全部内容为编造

   **重要判断标准**:
   - 如果回答中引用了具体的 ITU-R 建议书编号(如 M.2101, S.2368 等)但这些编号没有在参考答案中出现,且回答未标注来源,则视为编造文献,至少 0.4
   - 如果给出了具体的技术参数(如"最大 EIRP 为 XX dBW")但参考答案中没有这些数据,可能是编造
   - 如果输出了工具调用代码而不是实际回答,hallucination_score = 0.3（未提供有效回答,属于无效输出）

3. **completeness** (0~1): 相对于参考答案的要点覆盖度
   - 计算回答覆盖了参考答案中多少比例的关键要点
   - 如果输出工具调用代码或"信息不足",completeness = 0.0

## 输入

**问题**: {query}

**参考答案**: {reference_answer}

**待评答案**: {answer}

## 输出格式

请严格输出以下 JSON（不要加任何其他文字）:
```json
{{
  "answer_accuracy": 0.XX,
  "hallucination_score": 0.XX,
  "completeness": 0.XX,
  "reason": "一句话评价"
}}
```"""


async def judge_single(
    query: str,
    reference_answer: str,
    answer: str,
    client: httpx.AsyncClient,
) -> dict:
    """Call LLM judge to score a single answer."""
    prompt = JUDGE_PROMPT.format(
        query=query,
        reference_answer=reference_answer,
        answer=answer[:2000],  # limit length for judge
    )

    try:
        resp = await client.post(
            f"{BASE_URL}/api/eval/llm_only",
            json={"question": prompt},
            timeout=TIMEOUT,
        )
        if resp.status_code != 200:
            return {"answer_accuracy": 0.5, "hallucination_score": 0.5, "completeness": 0.5, "reason": "judge_error"}

        data = resp.json()
        text = data.get("answer", "")

        # Extract JSON from response
        json_match = re.search(r'\{[^{}]*"answer_accuracy"[^{}]*\}', text, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
            # Clamp values to [0, 1]
            for key in ["answer_accuracy", "hallucination_score", "completeness"]:
                if key in result:
                    result[key] = max(0.0, min(1.0, float(result[key])))
            return result

        return {"answer_accuracy": 0.5, "hallucination_score": 0.5, "completeness": 0.5, "reason": "parse_error: " + text[:100]}
    except Exception as e:
        return {"answer_accuracy": 0.5, "hallucination_score": 0.5, "completeness": 0.5, "reason": f"error: {str(e)[:80]}"}


async def run_judge(predictions: list[dict], questions: list[dict]) -> list[dict]:
    """Run LLM judge on all predictions."""
    q_map = {q["id"]: q for q in questions}
    judge_results = []

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        for i, pred in enumerate(predictions):
            qid = pred["question_id"]
            method = pred["method"]
            q = q_map.get(qid, {})
            ref = q.get("reference_answer", "")

            if not ref:
                judge_results.append({
                    "question_id": qid,
                    "method": method,
                    "answer_accuracy": 0.5,
                    "hallucination_score": 0.5,
                    "completeness": 0.5,
                    "reason": "no_reference_answer",
                })
                continue

            answer = pred.get("answer", "")
            print(f"  [{i+1}/{len(predictions)}] Judge {qid}/{method}...", end=" ", flush=True)
            result = await judge_single(q["query"], ref, answer, client)
            result["question_id"] = qid
            result["method"] = method
            judge_results.append(result)
            print(f"acc={result.get('answer_accuracy', '?')}")

    return judge_results


# ─── Scoring pipeline ───


def compute_final_score(
    source_hit: float,
    kw_cov: float,
    cite_acc: float,
    answer_acc: float,
    hallucination: float,
    completeness: float,
) -> float:
    """Weighted composite score (0~1)."""
    return (
        0.10 * source_hit
        + 0.15 * kw_cov
        + 0.15 * cite_acc
        + 0.30 * answer_acc
        + 0.15 * (1.0 - hallucination)  # invert: lower hallucination = better
        + 0.15 * completeness
    )


def score_predictions(
    predictions: list[dict],
    questions: list[dict],
    judge_results: list[dict] | None = None,
) -> list[dict]:
    """Score all predictions. Returns per-question-method metrics."""
    q_map = {q["id"]: q for q in questions}

    # Index judge results
    j_map: dict[str, dict] = {}
    if judge_results:
        for jr in judge_results:
            key = f"{jr['question_id']}_{jr['method']}"
            j_map[key] = jr

    rows = []
    for pred in predictions:
        qid = pred["question_id"]
        method = pred["method"]
        q = q_map.get(qid, {})

        # Source paths from retrieved blocks + citations
        retrieved_sources = [b.get("source_path", "") for b in pred.get("retrieved_blocks", [])]
        citation_sources = [c.get("source_path", c.get("source", "")) for c in pred.get("citations", [])]
        all_sources = [s for s in (retrieved_sources + citation_sources) if s]

        gold_patterns = q.get("gold_source_patterns", [])
        exp_keywords = q.get("expected_keywords", [])

        # Automatic metrics
        sh5 = source_hit_at_k(all_sources, gold_patterns, 5)
        answer = pred.get("answer", "")
        kw_cov = keyword_coverage(answer, exp_keywords)
        cite_ct = len(pred.get("citations", []))
        cite_acc = citation_accuracy(pred.get("citations", []), gold_patterns)

        # Judge metrics
        jkey = f"{qid}_{method}"
        j = j_map.get(jkey, {})
        ans_acc = j.get("answer_accuracy", None)
        hall_score = j.get("hallucination_score", None)
        completeness = j.get("completeness", None)
        reason = j.get("reason", "")

        # Final score (only if judge ran)
        final = None
        if ans_acc is not None:
            final = compute_final_score(sh5, kw_cov, cite_acc, ans_acc, hall_score or 0, completeness or 0)

        rows.append({
            "question_id": qid,
            "category": q.get("category", ""),
            "method": method,
            "source_hit_at_5": sh5,
            "keyword_coverage": round(kw_cov, 4),
            "citation_count": cite_ct,
            "citation_accuracy": round(cite_acc, 4),
            "answer_accuracy": round(ans_acc, 4) if ans_acc is not None else None,
            "hallucination_score": round(hall_score, 4) if hall_score is not None else None,
            "completeness": round(completeness, 4) if completeness is not None else None,
            "judge_reason": reason,
            "final_score": round(final, 4) if final is not None else None,
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

        # QA Accuracy = mean of answer_accuracy scores (continuous 0~1)
        acc_vals = [r["answer_accuracy"] for r in rows if r["answer_accuracy"] is not None]
        qa_accuracy = round(sum(acc_vals) / len(acc_vals), 4) if acc_vals else None

        summaries.append({
            "method": method,
            "qa_accuracy": qa_accuracy,
            "mean_answer_accuracy": avg("answer_accuracy"),
            "mean_completeness": avg("completeness"),
            "mean_hallucination_score": avg("hallucination_score"),
            "mean_source_hit_at_5": avg("source_hit_at_5"),
            "mean_keyword_coverage": avg("keyword_coverage"),
            "mean_citation_accuracy": avg("citation_accuracy"),
            "mean_final_score": avg("final_score"),
            "mean_latency_ms": avg("latency_ms"),
        })

    return summaries


def save_results(
    per_question: list[dict],
    summary: list[dict],
    judge_results: list[dict] | None,
    out_dir: Path,
):
    """Save all metrics files."""
    # Per-question CSV
    if per_question:
        csv_path = out_dir / "metrics_per_question.csv"
        with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(per_question[0].keys()))
            writer.writeheader()
            writer.writerows(per_question)
        print(f"Saved {csv_path}")

    # Summary CSV
    if summary:
        sum_csv = out_dir / "metrics_summary.csv"
        with open(sum_csv, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(summary[0].keys()))
            writer.writeheader()
            writer.writerows(summary)
        print(f"Saved {sum_csv}")

    # Summary JSON
    sum_json = out_dir / "metrics_summary.json"
    sum_json.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved {sum_json}")

    # Judge results
    if judge_results:
        jr_path = out_dir / "judge_results.jsonl"
        with open(jr_path, "w", encoding="utf-8") as f:
            for jr in judge_results:
                f.write(json.dumps(jr, ensure_ascii=False) + "\n")
        print(f"Saved {jr_path}")


# ─── CLI ───


def main():
    parser = argparse.ArgumentParser(description="Score RAG eval with LLM judge")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--questions", default="data/eval/rag_questions.jsonl")
    parser.add_argument("--no-judge", action="store_true", help="Skip LLM judge, use only automatic metrics")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)

    # Load predictions
    pred_path = run_dir / "raw_predictions.jsonl"
    predictions = []
    for line in pred_path.read_text(encoding="utf-8").strip().splitlines():
        if line.strip():
            predictions.append(json.loads(line))
    print(f"Loaded {len(predictions)} predictions")

    # Load questions
    questions = []
    qpath = Path(args.questions)
    if qpath.suffix == ".jsonl":
        for line in qpath.read_text(encoding="utf-8").strip().splitlines():
            if line.strip():
                questions.append(json.loads(line))
    else:
        questions = json.loads(qpath.read_text(encoding="utf-8"))
    print(f"Loaded {len(questions)} questions")

    # Run judge
    judge_results = None
    if not args.no_judge:
        print("\nRunning LLM judge...")
        judge_results = asyncio.run(run_judge(predictions, questions))
    else:
        # Try to load existing judge results
        jr_path = run_dir / "judge_results.jsonl"
        if jr_path.exists():
            judge_results = []
            for line in jr_path.read_text(encoding="utf-8").strip().splitlines():
                if line.strip():
                    judge_results.append(json.loads(line))
            print(f"Loaded existing judge results: {len(judge_results)}")

    # Score
    per_question = score_predictions(predictions, questions, judge_results)
    summary = summarize_metrics(per_question)

    # Save
    save_results(per_question, summary, judge_results, run_dir)

    # Print summary
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
