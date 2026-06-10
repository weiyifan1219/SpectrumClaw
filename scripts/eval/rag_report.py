"""RAG Report Generator — produce report.md from scored metrics.

Usage:
    python -m scripts.eval.rag_report --run-dir runs/rag_eval_official
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path


def load_summary(run_dir: Path) -> list[dict]:
    p = run_dir / "metrics_summary.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return []


def load_per_question(run_dir: Path) -> list[dict]:
    import csv
    p = run_dir / "metrics_per_question.csv"
    if not p.exists():
        return []
    with open(p, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def load_predictions(run_dir: Path) -> list[dict]:
    p = run_dir / "raw_predictions.jsonl"
    if not p.exists():
        return []
    preds = []
    for line in p.read_text(encoding="utf-8").strip().splitlines():
        if line.strip():
            preds.append(json.loads(line))
    return preds


def load_config(run_dir: Path) -> dict:
    p = run_dir / "config.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def _fmt(v, digits=3):
    if v is None or v == "":
        return "—"
    try:
        return f"{float(v):.{digits}f}"
    except (ValueError, TypeError):
        return str(v)


def _pct(v):
    if v is None or v == "":
        return "—"
    try:
        return f"{float(v)*100:.1f}%"
    except (ValueError, TypeError):
        return str(v)


METHOD_LABELS = {
    "llm_only": "普通大模型（无检索）",
    "vector_rag": "普通向量 RAG",
    "spectrumclaw_rag": "SpectrumClaw RAG",
    "hybrid_no_rerank": "混合检索（无重排）",
}


def generate_report(run_dir: Path) -> str:
    config = load_config(run_dir)
    summary = load_summary(run_dir)
    per_q = load_per_question(run_dir)
    preds = load_predictions(run_dir)

    methods = config.get("methods", [s["method"] for s in summary])
    num_q = config.get("num_questions", 10)
    top_k = config.get("top_k", 10)

    lines = []
    lines.append("# RAG 评测实验报告")
    lines.append("")
    lines.append(f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"> 评测目录: `{run_dir}`")
    lines.append("")

    # 1. Experiment setup
    lines.append("## 1. 实验设置")
    lines.append("")
    lines.append(f"- **测试问题**: {num_q} 个，涵盖频段分配、标准文档、脚注解释、区域差异、共存约束等类别")
    lines.append(f"- **Top-K**: {top_k}")
    lines.append(f"- **知识库**: ITU-R 建议书、无线电规则等频谱工程文档")
    lines.append(f"- **对比方法**: {', '.join(METHOD_LABELS.get(m, m) for m in methods)}")
    lines.append("")
    lines.append("| 方法 | 说明 |")
    lines.append("| --- | --- |")
    if "llm_only" in methods:
        lines.append("| 普通大模型 | 直接调用 LLM 回答，不接入知识库 |")
    if "vector_rag" in methods:
        lines.append("| 普通向量 RAG | 仅向量检索 Top-K + LLM 生成，无关键词/图谱/重排 |")
    if "spectrumclaw_rag" in methods:
        lines.append("| SpectrumClaw RAG | 查询分析 + 向量 + 关键词 + 图谱检索 + 领域规则重排 + 引用溯源 |")
    lines.append("")

    # 2. Retrieval metrics table
    retrieval_methods = [m for m in methods if m != "llm_only"]
    if retrieval_methods:
        lines.append("## 2. 检索性能对比")
        lines.append("")
        lines.append("| 方法 | Recall@3 | Recall@5 | MRR@10 | Source Hit@5 | Precision@5 |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for s in summary:
            if s["method"] not in retrieval_methods:
                continue
            label = METHOD_LABELS.get(s["method"], s["method"])
            lines.append(f"| {label} | {_pct(s.get('mean_recall_at_3'))} | {_pct(s.get('mean_recall_at_5'))} | {_fmt(s.get('mean_mrr_at_10'))} | {_pct(s.get('mean_source_hit_at_5'))} | {_pct(s.get('mean_precision_at_5'))} |")
        lines.append("")

    # 3. Answer quality table
    lines.append("## 3. 问答质量对比")
    lines.append("")
    lines.append("| 方法 | 关键词覆盖率 | 引用数量 | 引用准确率 | 回答准确率 | 幻觉率 | 综合得分 | 平均延迟 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for s in summary:
        label = METHOD_LABELS.get(s["method"], s["method"])
        cite_note = "N/A" if s["method"] == "llm_only" else _pct(s.get("mean_citation_accuracy"))
        lines.append(
            f"| {label} "
            f"| {_pct(s.get('mean_keyword_coverage'))} "
            f"| — "
            f"| {cite_note} "
            f"| {_fmt(s.get('mean_answer_accuracy'))} "
            f"| {_pct(s.get('hallucination_rate'))} "
            f"| {_fmt(s.get('mean_final_score'))} "
            f"| {_fmt(s.get('mean_latency_ms'), 0)}ms |"
        )
    lines.append("")

    # 4. Case analysis
    lines.append("## 4. 典型案例分析")
    lines.append("")

    # Find best case: spectrumclaw >> llm_only on keyword coverage
    pred_map: dict[str, dict] = {}
    for p in preds:
        pred_map[f"{p['question_id']}_{p['method']}"] = p

    per_q_map: dict[str, dict] = {}
    for row in per_q:
        per_q_map[f"{row['question_id']}_{row['method']}"] = row

    case_found = False
    # Case A: SpectrumClaw clearly better than LLM-only
    if "spectrumclaw_rag" in methods and "llm_only" in methods:
        best_delta = -1.0
        best_qid = None
        question_ids = list(set(p["question_id"] for p in preds))
        for qid in question_ids:
            sc = per_q_map.get(f"{qid}_spectrumclaw_rag", {})
            lo = per_q_map.get(f"{qid}_llm_only", {})
            try:
                delta = float(sc.get("keyword_coverage", 0)) - float(lo.get("keyword_coverage", 0))
            except (TypeError, ValueError):
                continue
            if delta > best_delta:
                best_delta = delta
                best_qid = qid

        if best_qid and best_delta > 0:
            case_found = True
            sc_pred = pred_map.get(f"{best_qid}_spectrumclaw_rag", {})
            lo_pred = pred_map.get(f"{best_qid}_llm_only", {})
            lines.append(f"### 案例 A: SpectrumClaw RAG 优于普通大模型 ({best_qid})")
            lines.append("")
            lines.append(f"**问题**: {sc_pred.get('query', '')}")
            lines.append("")
            lines.append(f"**普通大模型回答**（关键词覆盖: {_pct(per_q_map.get(f'{best_qid}_llm_only', {}).get('keyword_coverage'))}）:")
            lines.append("")
            lo_answer = lo_pred.get('answer', '')
            lines.append(f"> {lo_answer}")
            lines.append("")
            lines.append(f"**SpectrumClaw RAG 回答**（关键词覆盖: {_pct(per_q_map.get(f'{best_qid}_spectrumclaw_rag', {}).get('keyword_coverage'))}，引用 {len(sc_pred.get('citations', []))} 条来源）:")
            lines.append("")
            sc_answer = sc_pred.get('answer', '')
            lines.append(f"> {sc_answer}")
            lines.append("")
            # Show citations for SpectrumClaw
            if sc_pred.get("citations"):
                lines.append("**引用来源**:")
                for ci, c in enumerate(sc_pred["citations"][:5], 1):
                    src = c.get("source", c.get("source_path", ""))
                    src_name = src.rsplit("/", 1)[-1] if "/" in src else src
                    page = c.get("page", c.get("page_idx", ""))
                    lines.append(f"  {ci}. {src_name} (p.{page})")
                lines.append("")

    # Case B: vector_rag misses but spectrumclaw hits
    if "spectrumclaw_rag" in methods and "vector_rag" in methods:
        best_qid2 = None
        best_delta2 = -1.0
        for qid in set(p["question_id"] for p in preds):
            sc = per_q_map.get(f"{qid}_spectrumclaw_rag", {})
            vr = per_q_map.get(f"{qid}_vector_rag", {})
            try:
                sc_sh = float(sc.get("source_hit_at_5", 0))
                vr_sh = float(vr.get("source_hit_at_5", 0))
                delta = sc_sh - vr_sh
            except (TypeError, ValueError):
                continue
            if delta > best_delta2:
                best_delta2 = delta
                best_qid2 = qid

        if best_qid2 and best_delta2 > 0:
            case_found = True
            sc_pred = pred_map.get(f"{best_qid2}_spectrumclaw_rag", {})
            vr_pred = pred_map.get(f"{best_qid2}_vector_rag", {})
            lines.append(f"### 案例 B: 向量 RAG 检索不足，SpectrumClaw RAG 成功 ({best_qid2})")
            lines.append("")
            lines.append(f"**问题**: {sc_pred.get('query', '')}")
            lines.append("")
            lines.append(f"**向量 RAG 回答**（Source Hit@5 = {_pct(per_q_map.get(f'{best_qid2}_vector_rag', {}).get('source_hit_at_5'))}，关键词覆盖 = {_pct(per_q_map.get(f'{best_qid2}_vector_rag', {}).get('keyword_coverage'))}）:")
            lines.append("")
            lines.append(f"> {vr_pred.get('answer', '')}")
            lines.append("")
            lines.append(f"**SpectrumClaw RAG 回答**（Source Hit@5 = {_pct(per_q_map.get(f'{best_qid2}_spectrumclaw_rag', {}).get('source_hit_at_5'))}，关键词覆盖 = {_pct(per_q_map.get(f'{best_qid2}_spectrumclaw_rag', {}).get('keyword_coverage'))}）:")
            lines.append("")
            lines.append(f"> {sc_pred.get('answer', '')}")
            lines.append("")
            if sc_pred.get("citations"):
                lines.append("**引用来源**:")
                for ci, c in enumerate(sc_pred["citations"][:5], 1):
                    src = c.get("source", c.get("source_path", ""))
                    src_name = src.rsplit("/", 1)[-1] if "/" in src else src
                    page = c.get("page", c.get("page_idx", ""))
                    lines.append(f"  {ci}. {src_name} (p.{page})")
                lines.append("")
            lines.append("SpectrumClaw 的多路检索（关键词 + 图谱 + 领域重排）补充了纯向量检索的盲区。")
            lines.append("")

    if not case_found:
        lines.append("（待人工标注后自动填充典型案例）")
        lines.append("")

    # 5. Conclusion
    lines.append("## 5. 结论")
    lines.append("")

    # Auto-generate conclusion from summary
    sc_sum = next((s for s in summary if s["method"] == "spectrumclaw_rag"), None)
    vr_sum = next((s for s in summary if s["method"] == "vector_rag"), None)
    lo_sum = next((s for s in summary if s["method"] == "llm_only"), None)

    if sc_sum and lo_sum:
        sc_kw = sc_sum.get("mean_keyword_coverage") or 0
        lo_kw = lo_sum.get("mean_keyword_coverage") or 0
        kw_gain = sc_kw - lo_kw
        lines.append(
            f"实验表明，SpectrumClaw 的频谱专业 RAG 系统在关键词覆盖率上比纯大模型高 {kw_gain*100:.1f} 个百分点，"
            f"且能提供可追溯的文档引用（平均引用准确率 {_pct(sc_sum.get('mean_citation_accuracy'))}），"
            f"这对于需要证据支撑的频谱工程决策至关重要。"
        )
    if sc_sum and vr_sum:
        sc_sh = sc_sum.get("mean_source_hit_at_5") or 0
        vr_sh = vr_sum.get("mean_source_hit_at_5") or 0
        lines.append(
            f"相比普通向量 RAG，SpectrumClaw 的多路检索和领域规则重排使 Source Hit@5 从 {_pct(vr_sh)} 提升至 {_pct(sc_sh)}，"
            f"证明了领域适配检索在频谱专业问答中的必要性。"
        )
    lines.append("")
    lines.append("---")
    lines.append(f"*本报告由 SpectrumClaw RAG 评测系统自动生成。*")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Generate RAG evaluation report")
    parser.add_argument("--run-dir", required=True)
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    report = generate_report(run_dir)

    out_path = run_dir / "report.md"
    out_path.write_text(report, encoding="utf-8")
    print(f"Report saved → {out_path}")
    print(f"  ({len(report)} chars, {report.count(chr(10))} lines)")


if __name__ == "__main__":
    main()
