#!/usr/bin/env bash
# Generate the formal 5-band x 5-height corpus with 8 workers per RTX 3090.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
PYTHON=/root/miniconda3/envs/Agent_UAV/bin/python
WORKERS_PER_GPU=8
TOTAL_WORKERS=$((WORKERS_PER_GPU * 2))
MASTER_LOG="$ROOT/logs/data_generation.log"
PID_FILE="$ROOT/logs/data_generation_workers.tsv"

log() {
  printf '%s %s\n' "$(date --iso-8601=seconds)" "$*" | tee -a "$MASTER_LOG"
}

wait_workers() {
  local failures=0
  while IFS=$'\t' read -r name pid; do
    if wait "$pid"; then
      log "worker_completed name=$name pid=$pid"
    else
      log "worker_failed name=$name pid=$pid"
      failures=$((failures + 1))
    fi
  done < "$PID_FILE"
  if (( failures > 0 )); then
    log "ERROR worker_failures=$failures"
    return 1
  fi
}

launch_scenes() {
  rm -f "$PID_FILE"
  for ((worker=0; worker<TOTAL_WORKERS; worker++)); do
    local gpu=$((worker / WORKERS_PER_GPU))
    local layouts=()
    for ((layout=worker + 1; layout<=34; layout+=TOTAL_WORKERS)); do
      layouts+=("$layout")
    done
    local name
    name=$(printf 'scene_%02d' "$worker")
    CUDA_VISIBLE_DEVICES="$gpu" PYTHONPATH="$ROOT/src" "$PYTHON" -u \
      "$ROOT/scripts/generate_variants.py" --config "$ROOT/configs/dataset/scenes.yaml" \
      --layouts "${layouts[@]}" >> "$ROOT/logs/${name}.log" 2>&1 &
    printf '%s\t%s\n' "$name" "$!" >> "$PID_FILE"
    log "worker_started name=$name gpu=$gpu layouts=${layouts[*]} pid=$!"
  done
  wait_workers
}

launch_platform() {
  rm -f "$PID_FILE"
  local base_seed=2026130001
  local shard_size=256
  for ((worker=0; worker<TOTAL_WORKERS; worker++)); do
    local gpu=$((worker / WORKERS_PER_GPU))
    local seed=$((base_seed + worker * shard_size))
    local name output assets
    name=$(printf 'platform_%02d' "$worker")
    output="$ROOT/data/raw_gt/platform_multiband/shard_$(printf '%02d' "$worker")"
    assets="$ROOT/data/sionna_assets/platform_multiband/shard_$(printf '%02d' "$worker")"
    CUDA_VISIBLE_DEVICES="$gpu" PYTHONPATH="$ROOT/src" "$PYTHON" -u \
      "$ROOT/scripts/generate_dataset.py" --config "$ROOT/configs/dataset/platform.yaml" \
      --seed-start "$seed" --scene-count "$shard_size" --output "$output" --asset-dir "$assets" \
      >> "$ROOT/logs/${name}.log" 2>&1 &
    printf '%s\t%s\n' "$name" "$!" >> "$PID_FILE"
    log "worker_started name=$name gpu=$gpu seeds=$seed..$((seed + shard_size - 1)) pid=$!"
  done
  wait_workers
}

main() {
  local scope=${1:-all}
  [[ "$scope" == all || "$scope" == scenes || "$scope" == platform ]] || { echo "scope must be scenes/platform/all"; exit 2; }
  cd "$ROOT"
  mkdir -p logs data/raw_gt/multiband data/raw_gt/platform_multiband results/reports
  exec 8> "$ROOT/logs/data_generation.lock"
  flock -n 8 || { log "ERROR duplicate_data_controller"; exit 1; }
  log "formal_generation_started workers=$TOTAL_WORKERS samples_per_tx=10000000"
  if [[ "$scope" != platform ]]; then
    launch_scenes
    log "scene_generation_complete"
  fi
  if [[ "$scope" != scenes ]]; then
    launch_platform
    log "platform_generation_complete"
  fi
  "$PYTHON" - <<'PY' > results/reports/data_generation.json.tmp
import json
from pathlib import Path

root = Path.cwd()
scene_manifests = sorted((root / "data/raw_gt/multiband").glob("urban_layout_*/manifest.json"))
platform_manifests = sorted((root / "data/raw_gt/platform_multiband").glob("shard_*/manifest.json"))
def count(paths):
    return sum(json.loads(path.read_text())["sample_count"] for path in paths)
report = {
    "scene_layouts": len(scene_manifests),
    "scene_volumes": count(scene_manifests),
    "platform_shards": len(platform_manifests),
    "platform_volumes": count(platform_manifests),
}
print(json.dumps(report, indent=2))
PY
  mv results/reports/data_generation.json.tmp results/reports/data_generation.json
  log "formal_generation_complete"
}

main "$@"
