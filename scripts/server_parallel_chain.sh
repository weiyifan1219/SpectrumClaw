#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/workspace/YiFan/SpectrumClaw}"
ENV_DIR="${SPECTRUMCLAW_CONDA_ENV:-$PROJECT_ROOT/miniconda3/envs/SpectrumClaw}"
if [ ! -x "$ENV_DIR/bin/python" ]; then
  ENV_DIR="/root/miniconda3/envs/SpectrumClaw"
fi

cd "$PROJECT_ROOT"
mkdir -p data/logs data/mineru_cache

export PYTHONUNBUFFERED=1
export PATH="$ENV_DIR/bin:$PATH"
export LD_LIBRARY_PATH="$ENV_DIR/lib:/opt/nvidia/nsight-compute/2023.1.0/host/linux-desktop-glibc_2_11_3-x64/Mesa:${LD_LIBRARY_PATH:-}"
export HF_HOME="$PROJECT_ROOT/.cache/huggingface"
export TRANSFORMERS_CACHE="$HF_HOME/hub"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export MINERU_TOOLS_CONFIG_JSON="$PROJECT_ROOT/magic-pdf.json"
export MINERU_CACHE_DIR="$PROJECT_ROOT/data/mineru_cache"
export MINERU_PARSE_MODE="${MINERU_PARSE_MODE:-txt}"
export MINERU_TIMEOUT_SECONDS="${MINERU_TIMEOUT_SECONDS:-1200}"
export SPECTRUMCLAW_PARSER=mineru
export SPECTRUMCLAW_EMBEDDING_DEVICE="${SPECTRUMCLAW_EMBEDDING_DEVICE:-cuda}"
export SPECTRUMCLAW_EMBEDDING_FALLBACK=none

WORKERS="${MINERU_WORKERS:-2}"
IFS=',' read -r -a GPUS <<< "${MINERU_GPUS:-0,1}"
STAMP="${RUN_STAMP:-$(date +%Y%m%d_%H%M%S)}"
PIDS_FILE="data/mineru_preparse_${STAMP}.pids"
: > "$PIDS_FILE"

echo "PROJECT_ROOT=$PROJECT_ROOT"
echo "ENV_DIR=$ENV_DIR"
echo "WORKERS=$WORKERS"
echo "GPUS=${GPUS[*]}"
echo "MINERU_CACHE_DIR=$MINERU_CACHE_DIR"
echo "PDF_COUNT=$(find data/knowledge_base/raw -maxdepth 1 -type f -name '*.pdf' | wc -l)"
echo "STARTED_AT=$(date -Is)"

for worker in $(seq 0 $((WORKERS - 1))); do
  gpu="${GPUS[$((worker % ${#GPUS[@]}))]}"
  log="data/logs/mineru_preparse_${STAMP}_worker${worker}_gpu${gpu}.log"
  (
    export CUDA_VISIBLE_DEVICES="$gpu"
    exec "$ENV_DIR/bin/python" -u -m backend.rag.preparse_mineru \
      --shards "$WORKERS" \
      --shard-index "$worker"
  ) > "$log" 2>&1 &
  pid=$!
  echo "$pid $worker $gpu $log" | tee -a "$PIDS_FILE"
done

failures=0
while read -r pid worker gpu log; do
  if wait "$pid"; then
    echo "PREPARSE_WORKER_OK worker=$worker gpu=$gpu log=$log"
  else
    code=$?
    failures=$((failures + 1))
    echo "PREPARSE_WORKER_FAILED worker=$worker gpu=$gpu code=$code log=$log"
  fi
done < "$PIDS_FILE"

echo "PREPARSE_DONE failures=$failures at $(date -Is)"
if [ "$failures" -ne 0 ]; then
  exit 1
fi

ingest_log="data/logs/full_ingest_from_cache_${STAMP}.log"
echo "INGEST_START log=$ingest_log at $(date -Is)"
export CUDA_VISIBLE_DEVICES="${INGEST_CUDA_VISIBLE_DEVICES:-0}"
"$ENV_DIR/bin/python" -u -m backend.rag.ingest --clear > "$ingest_log" 2>&1
echo "INGEST_DONE log=$ingest_log at $(date -Is)"
