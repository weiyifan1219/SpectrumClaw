#!/bin/bash
# Launch GPU-accelerated MinerU preparse workers on both GPUs.
# Replaces the old CPU-bound subprocess-per-file approach.
#
# Usage: bash scripts/launch_gpu_preparse.sh [--force]

set -euo pipefail
cd /workspace/YiFan/SpectrumClaw

PYTHON="/workspace/YiFan/SpectrumClaw/miniconda3/envs/SpectrumClaw/bin/python"
LOG_DIR="data/logs"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
FORCE_FLAG="${1:-}"

mkdir -p "$LOG_DIR"

# Kill existing preparse workers (old CPU-based ones)
echo "[*] Stopping old preparse workers..."
pkill -f "preparse_mineru" 2>/dev/null && echo "    Killed old workers" || echo "    No old workers running"
sleep 2

# Launch GPU worker 0 on GPU 0
echo "[*] Launching GPU worker 0 on cuda:0..."
CUDA_VISIBLE_DEVICES=0 nohup $PYTHON -u -m backend.rag.preparse_gpu \
    --shards 2 --shard-index 0 $FORCE_FLAG \
    > "$LOG_DIR/preparse_gpu_${TIMESTAMP}_worker0.log" 2>&1 &
PID0=$!

# Launch GPU worker 1 on GPU 1
echo "[*] Launching GPU worker 1 on cuda:1..."
CUDA_VISIBLE_DEVICES=1 nohup $PYTHON -u -m backend.rag.preparse_gpu \
    --shards 2 --shard-index 1 $FORCE_FLAG \
    > "$LOG_DIR/preparse_gpu_${TIMESTAMP}_worker1.log" 2>&1 &
PID1=$!

# Save PID info
echo "$PID0 0 0 $LOG_DIR/preparse_gpu_${TIMESTAMP}_worker0.log" > "data/preparse_gpu_${TIMESTAMP}.pids"
echo "$PID1 1 1 $LOG_DIR/preparse_gpu_${TIMESTAMP}_worker1.log" >> "data/preparse_gpu_${TIMESTAMP}.pids"

echo "[*] Workers launched:"
echo "    Worker 0: PID=$PID0, GPU=0, log=$LOG_DIR/preparse_gpu_${TIMESTAMP}_worker0.log"
echo "    Worker 1: PID=$PID1, GPU=1, log=$LOG_DIR/preparse_gpu_${TIMESTAMP}_worker1.log"
echo ""
echo "[*] Monitor with:"
echo "    tail -f $LOG_DIR/preparse_gpu_${TIMESTAMP}_worker0.log"
echo "    tail -f $LOG_DIR/preparse_gpu_${TIMESTAMP}_worker1.log"
echo ""
echo "[*] GPU usage:"
nvidia-smi --query-gpu=index,memory.used,utilization.gpu --format=csv,noheader
