#!/usr/bin/env bash
# Wait for the immutable GT corpus, then pretrain and fine-tune automatically.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
PYTHON=/root/miniconda3/envs/Agent_UAV/bin/python
DATA_REPORT="$ROOT/results/reports/data_generation.json"
LOG="$ROOT/logs/pipeline.log"
export OMP_NUM_THREADS=4
export OPENBLAS_NUM_THREADS=1

log() {
  printf '%s %s\n' "$(date --iso-8601=seconds)" "$*" | tee -a "$LOG"
}

scenes_ready() {
  "$PYTHON" - "$ROOT" <<'PY'
import json, sys
from pathlib import Path
import yaml
root=Path(sys.argv[1])
plan=yaml.safe_load((root/"configs/dataset/scenes.yaml").read_text())
try:
    for layout in plan["layouts"]:
        directory=root/plan["output_root"]/f"urban_layout_{layout['layout_index']:02d}"
        manifest=json.loads((directory/"manifest.json").read_text())
        if manifest["sample_count"] != layout["source_count"] or len(manifest["samples"]) != layout["source_count"]:
            raise ValueError("incomplete manifest")
        if sum(1 for _ in (directory/layout["split"]).glob("*.npz")) != layout["source_count"]:
            raise ValueError("incomplete files")
except (OSError, ValueError, KeyError):
    raise SystemExit(1)
PY
}

wait_for_data() {
  local retries=0
  while ! scenes_ready; do
    local controller
    controller=$(cat "$ROOT/logs/data_generation.pid" 2>/dev/null || true)
    local state=""
    if [[ -n "$controller" ]]; then
      state=$(ps -o stat= -p "$controller" 2>/dev/null | tr -d '[:space:]' || true)
    fi
    if [[ -z "$state" || "$state" == Z* ]]; then
      # Do not start another writer while any old, orphaned worker is alive.
      if pgrep -f "^$PYTHON.*scripts/generate_(variants|dataset).py" >/dev/null; then
        sleep 60
        continue
      fi
      if (( retries >= 2 )); then
        log "ERROR generation_failed_after_two_resume_attempts"
        return 1
      fi
      retries=$((retries + 1))
      log "resuming_generation attempt=$retries"
      bash "$ROOT/scripts/run_data_generation.sh" scenes >> "$ROOT/logs/data_generation.stdout.log" 2>&1 &
      controller=$!
      printf '%s\n' "$controller" > "$ROOT/logs/data_generation.pid.tmp"
      mv "$ROOT/logs/data_generation.pid.tmp" "$ROOT/logs/data_generation.pid"
      wait "$controller" || log "generation_resume_failed attempt=$retries"
    fi
    sleep 60
  done
  log "scene_manifest_counts_ready awaiting_full_audit"
}

wait_for_gpus() {
  while nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | awk '$1 >= 500 {busy=1} END {exit !busy}'; do
    sleep 60
  done
}

run_stage() {
  local stage=$1
  log "training_started stage=$stage"
  CUDA_VISIBLE_DEVICES=0,1 PYTHONPATH="$ROOT/src" "$PYTHON" -u \
    "$ROOT/scripts/train_reconstructor.py" --stage "$stage" --device cuda --batch-size "$BATCH_SIZE" \
    >> "$ROOT/logs/${stage}.stdout.log" 2>&1
  log "training_completed stage=$stage"
}

main() {
  cd "$ROOT"
  mkdir -p logs checkpoints/reconstructor/pretrain checkpoints/reconstructor/finetune results/reports
  exec 9> "$ROOT/logs/pipeline.lock"
  flock -n 9 || { log "pipeline_already_running"; exit 1; }
  "$PYTHON" "$ROOT/scripts/check_storage.py" "$ROOT/data/raw_gt"
  "$PYTHON" "$ROOT/scripts/check_storage.py" "$ROOT/checkpoints"
  if [[ "${1:-}" == --recover ]]; then
    log "recovering_verified_samples_and_manifests"
    "$PYTHON" -u "$ROOT/scripts/repair_corpus.py" > "$ROOT/logs/data_recovery.log" 2>&1
  fi
  log "pipeline_waiting_for_data"
  wait_for_data | tee -a "$LOG"
  log "auditing_all_samples"
  "$PYTHON" -u "$ROOT/scripts/audit_corpus.py" --scope scenes --workers 8 > "$ROOT/logs/data_audit.log" 2>&1
  log "data_audit_passed"
  wait_for_gpus
  CUDA_VISIBLE_DEVICES=0,1 PYTHONPATH="$ROOT/src" "$PYTHON" -u "$ROOT/scripts/check_training.py" > "$ROOT/logs/training_check.log" 2>&1
  BATCH_SIZE=$("$PYTHON" -c 'import json; print(json.load(open("results/reports/training_check.json"))["batch_size"])')
  run_stage pretrain
  run_stage finetune
  log "fixed_budget_evaluation_started"
  CUDA_VISIBLE_DEVICES=0 PYTHONPATH="$ROOT/src" "$PYTHON" -u "$ROOT/scripts/evaluate_reconstructor.py" \
    --stage finetune --split test --rates 0 0.01 0.03 0.05 --batch-size 32 \
    --output "$ROOT/results/reports/finetune_by_budget.json" > "$ROOT/logs/evaluation.log" 2>&1
  log "generating_held_out_platform_test_data"
  bash "$ROOT/scripts/run_data_generation.sh" platform >> "$ROOT/logs/data_generation.stdout.log" 2>&1
  "$PYTHON" -u "$ROOT/scripts/audit_corpus.py" --scope platform --workers 8 > "$ROOT/logs/platform_audit.log" 2>&1
  wait_for_gpus
  CUDA_VISIBLE_DEVICES=0 PYTHONPATH="$ROOT/src" "$PYTHON" -u "$ROOT/scripts/evaluate_reconstructor.py" \
    --stage finetune --split test --platform --rates 0 0.01 0.03 0.05 --batch-size 32 \
    --output "$ROOT/results/reports/platform_by_budget.json" >> "$ROOT/logs/evaluation.log" 2>&1
  log "pipeline_complete"
}

main "$@"
