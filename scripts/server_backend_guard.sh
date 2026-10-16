#!/usr/bin/env bash
# Keep the production frontend and API on one fixed port in non-systemd hosts.
set -uo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_ROOT="${SPECTRUMCLAW_UAV_RUNTIME_ROOT:-/root/autodl-tmp/spectrumclaw/runtime}"
STATE_ROOT="${SPECTRUMCLAW_SERVICE_ROOT:-/root/autodl-tmp/spectrumclaw}"
PYTHON_BIN="${SPECTRUMCLAW_PYTHON_BIN:-/root/miniconda3/envs/SpectrumClaw/bin/python}"
PORT=8230
HEALTH_URL="http://127.0.0.1:${PORT}/health"
mkdir -p "$STATE_ROOT/services" "$STATE_ROOT/logs"
exec 9>"$STATE_ROOT/services/backend-guard.lock"
flock -n 9 || exit 0

cd "$PROJECT_ROOT" || exit 1
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "[$(date -Is)] missing Python runtime: $PYTHON_BIN" >> "$STATE_ROOT/logs/backend-guard.log"
  exit 1
fi

export SPECTRUMCLAW_AGENT_RUNTIME="${SPECTRUMCLAW_AGENT_RUNTIME:-langgraph}"
export SPECTRUMCLAW_UAV_RUNTIME_ROOT="$RUNTIME_ROOT"
export SPECTRUMCLAW_UAV_PROJECT_ROOT="$PROJECT_ROOT"
export SPECTRUMCLAW_PX4_DIR="${SPECTRUMCLAW_PX4_DIR:-$PROJECT_ROOT/simulation/third_party/PX4-Autopilot}"
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"

healthy() { curl -fsS --max-time 5 "$HEALTH_URL" >/dev/null 2>&1; }
backend_pid() { cat "$STATE_ROOT/services/backend.pid" 2>/dev/null || true; }
is_backend_pid() {
  local pid="$1"
  [[ "$pid" =~ ^[0-9]+$ ]] &&
    kill -0 "$pid" 2>/dev/null &&
    ps -p "$pid" -o args= | grep -Fq -- "uvicorn backend.app:app --host 0.0.0.0 --port $PORT"
}

while true; do
  if healthy; then
    # Adopt a working backend started before this guard, preserving its live map.
    failures=0
    while healthy; do
      sleep 10
    done
    while (( failures < 2 )); do
      sleep 5
      if healthy; then break; fi
      failures=$((failures + 1))
    done
    if healthy; then continue; fi
  fi

  old_pid="$(backend_pid)"
  if is_backend_pid "$old_pid"; then
    kill "$old_pid" 2>/dev/null || true
    for (( attempt=0; attempt<5; attempt++ )); do
      if ! is_backend_pid "$old_pid"; then break; fi
      sleep 1
    done
    if is_backend_pid "$old_pid"; then
      pkill -TERM -P "$old_pid" 2>/dev/null || true
      kill -KILL "$old_pid" 2>/dev/null || true
    fi
  fi
  echo "[$(date -Is)] starting backend on port $PORT" >> "$STATE_ROOT/logs/backend-guard.log"
  "$PYTHON_BIN" -m uvicorn backend.app:app --host 0.0.0.0 --port "$PORT" --log-level info \
    >> "$STATE_ROOT/logs/backend.log" 2>&1 &
  child_pid=$!
  echo "$child_pid" > "$STATE_ROOT/services/backend.pid"
  for (( attempt=0; attempt<30; attempt++ )); do
    if healthy; then break; fi
    if ! kill -0 "$child_pid" 2>/dev/null; then break; fi
    sleep 2
  done
  if ! healthy; then
    echo "[$(date -Is)] backend failed to become healthy" >> "$STATE_ROOT/logs/backend-guard.log"
    kill "$child_pid" 2>/dev/null || true
    sleep 5
  fi
done
