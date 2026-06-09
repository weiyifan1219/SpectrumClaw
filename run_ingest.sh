#!/usr/bin/env bash
set -euo pipefail

cd /workspace/YiFan/SpectrumClaw
mkdir -p data/logs

LOG="data/logs/parallel_mineru_chain_$(date +%Y%m%d_%H%M%S).log"
nohup bash scripts/server_parallel_chain.sh > "$LOG" 2>&1 &
PID=$!

echo "$PID" > data/ingest.pid
echo "PID=$PID"
echo "LOG=$LOG"
