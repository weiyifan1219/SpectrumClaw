#!/usr/bin/env bash
# RAG 评测实验 — 运行完整三组对比并生成报告
# 使用方式: bash scripts/eval/run_rag_eval.sh
set -e
cd "$(dirname "$0")/../.."

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUT_DIR="runs/rag_eval_${TIMESTAMP}"

echo "╔════════════════════════════════════════════════╗"
echo "║  SpectrumClaw RAG 评测实验                      ║"
echo "╚════════════════════════════════════════════════╝"
echo ""
echo "输出目录: ${OUT_DIR}"
echo ""

# Step 1: 运行三组对比实验
echo "▶ Step 1: 运行实验 (llm_only / vector_rag / spectrumclaw_rag)"
python3 -m scripts.eval.rag_eval \
  --questions data/eval/rag_questions.jsonl \
  --methods llm_only,vector_rag,spectrumclaw_rag \
  --top-k 10 \
  --out "${OUT_DIR}"

# Step 2: 计算指标
echo ""
echo "▶ Step 2: 计算指标"
python3 -m scripts.eval.rag_score \
  --run-dir "${OUT_DIR}" \
  --gold data/eval/rag_gold.jsonl \
  --questions data/eval/rag_questions.jsonl

# Step 3: 生成报告
echo ""
echo "▶ Step 3: 生成报告"
python3 -m scripts.eval.rag_report \
  --run-dir "${OUT_DIR}"

echo ""
echo "════════════════════════════════════════════════"
echo "完成! 结果目录: ${OUT_DIR}"
echo ""
echo "  报告:    ${OUT_DIR}/report.md"
echo "  指标:    ${OUT_DIR}/metrics_summary.json"
echo "  详细:    ${OUT_DIR}/metrics_per_question.csv"
echo "  原始:    ${OUT_DIR}/raw_predictions.jsonl"
echo "  人工评分: ${OUT_DIR}/human_judgement_template.csv"
echo ""
echo "下一步:"
echo "  1. 填写 human_judgement_template.csv 中的 answer_accuracy (0-2) 和 hallucination_flag (0/1)"
echo "  2. 重新运行评分: python3 -m scripts.eval.rag_score --run-dir ${OUT_DIR} --gold data/eval/rag_gold.jsonl"
echo "  3. 重新生成报告: python3 -m scripts.eval.rag_report --run-dir ${OUT_DIR}"
