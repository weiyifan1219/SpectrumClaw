#!/usr/bin/env bash
set -euo pipefail

ROOT=/dev/shm/uav_rem_active_mapping
PYTHON=/root/miniconda3/envs/Agent_UAV/bin/python
export PYTHONPATH="$ROOT/src:/workspace/YiFan/SpectrumClaw"
export OMP_NUM_THREADS=4
export OPENBLAS_NUM_THREADS=1

log() { printf '%s %s\n' "$(date --iso-8601=seconds)" "$*" | tee -a "$ROOT/logs/shm_pipeline.log"; }

while [[ ! -s "$ROOT/results/reports/shm_generation.json" ]]; do
  pid=$(cat "$ROOT/logs/rebuild_controller.pid" 2>/dev/null || true)
  state=$(ps -o stat= -p "$pid" 2>/dev/null | tr -d '[:space:]' || true)
  [[ -n "$state" && "$state" != Z* ]] || { log "ERROR rebuild_stopped"; exit 1; }
  sleep 60
done

log "generation_complete_waiting_for_local_backup"
while [[ ! -f "$ROOT/results/reports/local_backup_complete" ]]; do sleep 60; done

log "auditing_full_scene_corpus"
"$PYTHON" -u "$ROOT/scripts/audit_corpus.py" --scope scenes --workers 8 > "$ROOT/logs/data_audit.log" 2>&1
log "data_audit_passed"

CUDA_VISIBLE_DEVICES=0,1 "$PYTHON" -u "$ROOT/scripts/check_training.py" > "$ROOT/logs/training_check.log" 2>&1
BATCH_SIZE=$("$PYTHON" -c 'import json; print(json.load(open("results/reports/training_check.json"))["batch_size"])')
log "training_check_passed batch=$BATCH_SIZE"

CUDA_VISIBLE_DEVICES=0,1 "$PYTHON" -u "$ROOT/scripts/train_reconstructor.py" --stage pretrain --batch-size "$BATCH_SIZE" >> "$ROOT/logs/pretrain.stdout.log" 2>&1
log "pretrain_complete"
CUDA_VISIBLE_DEVICES=0,1 "$PYTHON" -u "$ROOT/scripts/train_reconstructor.py" --stage finetune --batch-size "$BATCH_SIZE" >> "$ROOT/logs/finetune.stdout.log" 2>&1
log "finetune_complete"
CUDA_VISIBLE_DEVICES=0 "$PYTHON" -u "$ROOT/scripts/evaluate_reconstructor.py" --stage finetune --split test \
  --rates 0 0.01 0.03 0.05 --batch-size 32 --output "$ROOT/results/reports/finetune_by_budget.json" > "$ROOT/logs/evaluation.log" 2>&1
log "pipeline_complete"
