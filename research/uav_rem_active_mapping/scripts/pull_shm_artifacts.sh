#!/usr/bin/env bash
# Run on the local Codex host. Pulls the RAM-disk corpus before training starts,
# then mirrors checkpoints after every completed epoch.
set -euo pipefail

REMOTE=weiyifan3090
REMOTE_ROOT=/dev/shm/uav_rem_active_mapping
LOCAL_ROOT=/home/weiyifan/workspace/SpectrumClaw/research/uav_rem_active_mapping
LOG="$LOCAL_ROOT/logs/shm_pull.log"
mkdir -p "$LOCAL_ROOT/logs" "$LOCAL_ROOT/data/raw_gt" "$LOCAL_ROOT/checkpoints/reconstructor"

while ! ssh "$REMOTE" "test -s $REMOTE_ROOT/results/reports/shm_generation.json"; do sleep 60; done

incoming="$LOCAL_ROOT/data/raw_gt/multiband.incoming"
rm -rf "$incoming"
mkdir -p "$incoming"
ssh "$REMOTE" "tar -C $REMOTE_ROOT/data/raw_gt/multiband -cf - ." | tar -C "$incoming" -xf -
count=$(find "$incoming" -name '*.npz' | wc -l)
[[ "$count" -eq 17408 ]] || { echo "dataset copy count=$count" >> "$LOG"; exit 1; }
rm -rf "$LOCAL_ROOT/data/raw_gt/multiband"
mv "$incoming" "$LOCAL_ROOT/data/raw_gt/multiband"
ssh "$REMOTE" "touch $REMOTE_ROOT/results/reports/local_backup_complete"
printf '%s dataset_backup_complete count=%s\n' "$(date --iso-8601=seconds)" "$count" >> "$LOG"

last_epoch=-1
while true; do
  epoch=$(ssh "$REMOTE" "test -f $REMOTE_ROOT/logs/pretrain.jsonl && wc -l < $REMOTE_ROOT/logs/pretrain.jsonl || echo 0")
  fine_epoch=$(ssh "$REMOTE" "test -f $REMOTE_ROOT/logs/finetune.jsonl && wc -l < $REMOTE_ROOT/logs/finetune.jsonl || echo 0")
  marker="$epoch:$fine_epoch"
  if [[ "$marker" != "$last_epoch" ]]; then
    for stage in pretrain finetune; do
      mkdir -p "$LOCAL_ROOT/checkpoints/reconstructor/$stage"
      for file in best.pt last.pt normalization.json; do
        if ssh "$REMOTE" "test -f $REMOTE_ROOT/checkpoints/reconstructor/$stage/$file"; then
          scp "$REMOTE:$REMOTE_ROOT/checkpoints/reconstructor/$stage/$file" "$LOCAL_ROOT/checkpoints/reconstructor/$stage/$file.tmp"
          mv "$LOCAL_ROOT/checkpoints/reconstructor/$stage/$file.tmp" "$LOCAL_ROOT/checkpoints/reconstructor/$stage/$file"
        fi
      done
    done
    last_epoch="$marker"
    printf '%s checkpoint_sync epochs=%s\n' "$(date --iso-8601=seconds)" "$marker" >> "$LOG"
  fi
  if ssh "$REMOTE" "grep -q pipeline_complete $REMOTE_ROOT/logs/shm_pipeline.log 2>/dev/null"; then break; fi
  if ssh "$REMOTE" "grep -q 'ERROR' $REMOTE_ROOT/logs/shm_pipeline.log 2>/dev/null"; then exit 1; fi
  sleep 120
done
ssh "$REMOTE" "tar -C $REMOTE_ROOT -cf - results logs" | tar -C "$LOCAL_ROOT" -xf -
