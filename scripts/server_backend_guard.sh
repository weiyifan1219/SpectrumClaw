#!/usr/bin/env bash
set -uo pipefail

PROJECT_ROOT="/workspace/YiFan/SpectrumClaw"
PYTHON_BIN="/root/miniconda3/envs/SpectrumClaw/bin/python"
BACKEND_LOG="/tmp/spectrumclaw_backend.log"
GUARD_LOG="/tmp/spectrumclaw_backend_guard.log"

cd "$PROJECT_ROOT"

if [ ! -x "$PYTHON_BIN" ]; then
  echo "[backend-guard] missing Python runtime: $PYTHON_BIN" >&2
  exit 1
fi

stop_requested=0
child_pid=""

stop_child() {
  stop_requested=1
  if [ -n "$child_pid" ]; then
    kill "$child_pid" 2>/dev/null || true
  fi
}

trap stop_child INT TERM

while true; do
  echo "[$(date -Is)] starting backend" >> "$GUARD_LOG"
  "$PYTHON_BIN" -m uvicorn backend.app:create_app --factory \
    --host 0.0.0.0 --port 8230 >> "$BACKEND_LOG" 2>&1 &
  child_pid=$!
  wait "$child_pid"
  exit_code=$?
  child_pid=""

  if [ "$stop_requested" -eq 1 ]; then
    exit 0
  fi

  echo "[$(date -Is)] backend exited with code $exit_code; restarting" >> "$GUARD_LOG"
  sleep 5
done
