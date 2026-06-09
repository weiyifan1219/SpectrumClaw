#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/workspace/YiFan/SpectrumClaw}"
ENV_DIR="${SPECTRUMCLAW_CONDA_ENV:-$PROJECT_ROOT/miniconda3/envs/SpectrumClaw}"
if [ ! -x "$ENV_DIR/bin/python" ]; then
  ENV_DIR="/root/miniconda3/envs/SpectrumClaw"
fi

cd "$PROJECT_ROOT"

export PYTHONUNBUFFERED=1
export PATH="$ENV_DIR/bin:$PATH"
export LD_LIBRARY_PATH="$ENV_DIR/lib:/opt/nvidia/nsight-compute/2023.1.0/host/linux-desktop-glibc_2_11_3-x64/Mesa:${LD_LIBRARY_PATH:-}"
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"

export HF_HOME="$PROJECT_ROOT/.cache/huggingface"
export TRANSFORMERS_CACHE="$HF_HOME/hub"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export MINERU_TOOLS_CONFIG_JSON="$PROJECT_ROOT/magic-pdf.json"
export MINERU_CACHE_DIR="$PROJECT_ROOT/data/mineru_cache"

export SPECTRUMCLAW_PARSER=mineru
export MINERU_PARSE_MODE="${MINERU_PARSE_MODE:-txt}"
export MINERU_TIMEOUT_SECONDS="${MINERU_TIMEOUT_SECONDS:-1200}"
export SPECTRUMCLAW_EMBEDDING_DEVICE="${SPECTRUMCLAW_EMBEDDING_DEVICE:-cuda}"
export SPECTRUMCLAW_EMBEDDING_FALLBACK=none

echo "PROJECT_ROOT=$PROJECT_ROOT"
echo "ENV_DIR=$ENV_DIR"
echo "CUDA_VISIBLE_DEVICES=$CUDA_VISIBLE_DEVICES"
echo "HF_HOME=$HF_HOME"
echo "MINERU_TOOLS_CONFIG_JSON=$MINERU_TOOLS_CONFIG_JSON"
echo "MINERU_CACHE_DIR=$MINERU_CACHE_DIR"
echo "PDF_COUNT=$(find data/knowledge_base/raw -maxdepth 1 -type f -name '*.pdf' | wc -l)"
echo "STARTED_AT=$(date -Is)"

exec "$ENV_DIR/bin/python" -u -m backend.rag.ingest --clear
