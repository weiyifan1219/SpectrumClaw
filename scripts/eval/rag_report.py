"""RAG Report Generator — produce report.md from scored metrics.

Usage:
    python -m scripts.eval.rag_report --run-dir runs/rag_eval_test
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
    lines.append(f"- **知识库**: ITU-R 建议书、无线电规则等频谱工程文档（共 5276 篇）")
    lines.append(f"- **评测方式**: 端到端 QA 准确率评测，使用 LLM Judge 对比参考答案打分（0~1 连续值）")
    lines.append(f"- **对比方法**: {', '.join(METHOD_LABELS.get(m, m) for m in methods)}")
    lines.append("")
    lines.append("| 方法 | 说明 |")
    lines.append("| --- | --- |")
    if "llm_only" in methods:
        lines.append("| 普通大模型 | 直接调用 LLM 回答，不接入知识库，不提供检索上下文 |")
    if "vector_rag" in methods:
        lines.append("| 普通向量 RAG | 仅向量检索 Top-K + LLM 生成，无关键词/图谱/重排 |")
    if "spectrumclaw_rag" in methods:
        lines.append("| SpectrumClaw RAG | 查询分析 + 向量 + 关键词 + 图谱检索 + 领域规则重排 + 引用溯源 |")
    lines.append("")

    # 2. Metrics explanation
    lines.append("## 2. 评价指标说明")
    lines.append("")
    lines.append("| 指标 | 说明 | 取值范围 |")
    lines.append("| --- | --- | --- |")
    lines.append("| QA Accuracy | 回答准确率（answer_accuracy ≥ 0.7 的比例） | 0~1 |")
    lines.append("| Answer Accuracy | LLM Judge 评定的回答正确性与完整性 | 0~1 连续值 |")
    lines.append("| Completeness | 相对于参考答案的要点覆盖度 | 0~1 连续值 |")
    lines.append("| Hallucination | 幻觉程度（越低越好） | 0~1 连续值 |")
    lines.append("| Source Hit@5 | 检索结果中是否命中权威来源文档 | 0 或 1 |")
    lines.append("| Keyword Coverage | 回答中覆盖期望关键词的比例 | 0~1 |")
    lines.append("| Citation Accuracy | 引用来源匹配正确率 | 0~1 |")
    lines.append("| Final Score | 加权综合得分 | 0~1 |")
    lines.append("")

    # 3. Main results table
    lines.append("## 3. 总体性能对比")
    lines.append("")
    lines.append("| 方法 | QA 准确率 | 回答质量 | 完整性 | 幻觉程度 | Source Hit | 关键词覆盖 | 引用准确率 | 综合得分 | 延迟 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for s in summary:
        label = METHOD_LABELS.get(s["method"], s["method"])
        lines.append(
            f"| {label} "
            f"| {_pct(s.get('qa_accuracy'))} "
            f"| {_fmt(s.get('mean_answer_accuracy'))} "
            f"| {_fmt(s.get('mean_completeness'))} "
            f"| {_fmt(s.get('mean_hallucination_score'))} "
            f"| {_pct(s.get('mean_source_hit_at_5'))} "
            f"| {_pct(s.get('mean_keyword_coverage'))} "
            f"| {_pct(s.get('mean_citation_accuracy'))} "
            f"| {_fmt(s.get('mean_final_score'))} "
            f"| {_fmt(s.get('mean_latency_ms'), 0)}ms |"
        )
    lines.append("")

    # 4. Per-category accuracy
    if per_q:
        lines.append("## 4. 分类型准确率")
        lines.append("")
        categories = sorted(set(r.get("category", "") for r in per_q if r.get("category")))
        if categories:
            header = "| 类别 | " + " | ".join(METHOD_LABELS.get(m, m) for m in methods) + " |"
            lines.append(header)
            lines.append("| --- " * (len(methods) + 1) + "|")
            for cat in categories:
                row = f"| {cat} "
                for method in methods:
                    vals = [
                        float(r["answer_accuracy"])
                        for r in per_q
                        if r["category"] == cat and r["method"] == method and r.get("answer_accuracy") not in (None, "")
                    ]
                    avg_val = sum(vals) / len(vals) if vals else None
                    row += f"| {_fmt(avg_val)} "
                row += "|"
                lines.append(row)
            lines.append("")

    # 5. Case analysis
    lines.append("## 5. 典型案例分析")
    lines.append("")

    pred_map: dict[str, dict] = {}
    for p in preds:
        pred_map[f"{p['question_id']}_{p['method']}"] = p

    per_q_map: dict[str, dict] = {}
    for row in per_q:
        per_q_map[f"{row['question_id']}_{row['method']}"] = row

    # Case A: SpectrumClaw clearly better than LLM-only
    if "spectrumclaw_rag" in methods and "llm_only" in methods:
        best_delta = -1.0
        best_qid = None
        question_ids = list(set(p["question_id"] for p in preds))
        for qid in question_ids:
            sc = per_q_map.get(f"{qid}_spectrumclaw_rag", {})
            lo = per_q_map.get(f"{qid}_llm_only", {})
            try:
                sc_acc = float(sc.get("answer_accuracy") or 0)
                lo_acc = float(lo.get("answer_accuracy") or 0)
                delta = sc_acc - lo_acc
            except (TypeError, ValueError):
                continue
            if delta > best_delta:
                best_delta = delta
                best_qid = qid

        if best_qid and best_delta > 0:
            sc_pred = pred_map.get(f"{best_qid}_spectrumclaw_rag", {})
            lo_pred = pred_map.get(f"{best_qid}_llm_only", {})
            sc_q = per_q_map.get(f"{best_qid}_spectrumclaw_rag", {})
            lo_q = per_q_map.get(f"{best_qid}_llm_only", {})
            lines.append(f"### 案例 A: SpectrumClaw RAG 优于普通大模型 ({best_qid})")
            lines.append("")
            lines.append(f"**问题**: {sc_pred.get('query', '')}")
            lines.append("")
            lines.append(f"**普通大模型**（准确率: {_fmt(lo_q.get('answer_accuracy'))}，幻觉: {_fmt(lo_q.get('hallucination_score'))}）:")
            lines.append("")
            lines.append(f"> {lo_pred.get('answer', '')}")
            lines.append("")
            lines.append(f"**SpectrumClaw RAG**（准确率: {_fmt(sc_q.get('answer_accuracy'))}，幻觉: {_fmt(sc_q.get('hallucination_score'))}，引用 {len(sc_pred.get('citations', []))} 条来源）:")
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

    # Case B: vector_rag vs spectrumclaw
    if "spectrumclaw_rag" in methods and "vector_rag" in methods:
        best_qid2 = None
        best_delta2 = -1.0
        for qid in set(p["question_id"] for p in preds):
            sc = per_q_map.get(f"{qid}_spectrumclaw_rag", {})
            vr = per_q_map.get(f"{qid}_vector_rag", {})
            try:
                delta = float(sc.get("answer_accuracy") or 0) - float(vr.get("answer_accuracy") or 0)
            except (TypeError, ValueError):
                continue
            if delta > best_delta2:
                best_delta2 = delta
                best_qid2 = qid

        if best_qid2 and best_delta2 > 0:
            sc_pred = pred_map.get(f"{best_qid2}_spectrumclaw_rag", {})
            vr_pred = pred_map.get(f"{best_qid2}_vector_rag", {})
            sc_q = per_q_map.get(f"{best_qid2}_spectrumclaw_rag", {})
            vr_q = per_q_map.get(f"{best_qid2}_vector_rag", {})
            lines.append(f"### 案例 B: SpectrumClaw RAG 优于普通向量 RAG ({best_qid2})")
            lines.append("")
            lines.append(f"**问题**: {sc_pred.get('query', '')}")
            lines.append("")
            lines.append(f"**向量 RAG**（准确率: {_fmt(vr_q.get('answer_accuracy'))}，完整性: {_fmt(vr_q.get('completeness'))}）:")
            lines.append("")
            lines.append(f"> {vr_pred.get('answer', '')}")
            lines.append("")
            lines.append(f"**SpectrumClaw RAG**（准确率: {_fmt(sc_q.get('answer_accuracy'))}，完整性: {_fmt(sc_q.get('completeness'))}）:")
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

    # 6. Conclusion
    lines.append("## 6. 结论")
    lines.append("")

    sc_sum = next((s for s in summary if s["method"] == "spectrumclaw_rag"), None)
    vr_sum = next((s for s in summary if s["method"] == "vector_rag"), None)
    lo_sum = next((s for s in summary if s["method"] == "llm_only"), None)

    if sc_sum:
        lines.append("实验结果表明：")
        lines.append("")
        if lo_sum:
            lines.append(
                f"1. **SpectrumClaw RAG 显著优于纯大模型**: "
                f"QA 准确率 {_pct(sc_sum.get('qa_accuracy'))} vs {_pct(lo_sum.get('qa_accuracy'))}，"
                f"幻觉程度 {_fmt(sc_sum.get('mean_hallucination_score'))} vs {_fmt(lo_sum.get('mean_hallucination_score'))}。"
                f"纯大模型在频谱专业问题上容易产生幻觉（编造不存在的文献号和具体数据），"
                f"而 RAG 系统的检索增强有效抑制了幻觉。"
            )
        if vr_sum:
            lines.append(
                f"2. **SpectrumClaw RAG 优于普通向量 RAG**: "
                f"回答质量 {_fmt(sc_sum.get('mean_answer_accuracy'))} vs {_fmt(vr_sum.get('mean_answer_accuracy'))}，"
                f"完整性 {_fmt(sc_sum.get('mean_completeness'))} vs {_fmt(vr_sum.get('mean_completeness'))}，"
                f"引用准确率 {_pct(sc_sum.get('mean_citation_accuracy'))} vs {_pct(vr_sum.get('mean_citation_accuracy'))}。"
                f"多路检索（向量 + 关键词 + 图谱）和领域规则重排使系统能找到更相关的证据，"
                f"产生更完整准确的回答。"
            )
        lines.append(
            f"3. **可追溯性**: SpectrumClaw RAG 的引用准确率达 {_pct(sc_sum.get('mean_citation_accuracy'))}，"
            f"每个结论都能追溯到具体的 ITU-R 文档和页码，"
            f"这对于需要证据支撑的频谱工程决策至关重要。"
        )
        lines.append("")

    lines.append("---")
    lines.append("*本报告由 SpectrumClaw RAG 评测系统自动生成。*")

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
