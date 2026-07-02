#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="/home/weiyifan/workspace/SpectrumClaw"
SSH_KEY="/home/weiyifan/.ssh/27_4000"
SSH_TARGET="root@162.18.1.4"
REMOTE_ROOT="/workspace/YiFan/SpectrumClaw"
JUMP_HOST="172.18.101.27"
JUMP_PORT="4000"
PROXY_JUMP="ssh -F /dev/null -i $SSH_KEY -p $JUMP_PORT -o IdentitiesOnly=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -W 162.18.1.4:22 root@$JUMP_HOST"

INTERVAL_SECONDS="${VLM_MONITOR_INTERVAL_SECONDS:-600}"
LOG_FILE="${VLM_MONITOR_LOG_FILE:-/tmp/spectrumclaw_vlm_monitor.log}"
LATEST_FILE="${VLM_MONITOR_LATEST_FILE:-/tmp/spectrumclaw_vlm_monitor.latest}"
PID_FILE="${VLM_MONITOR_PID_FILE:-/tmp/spectrumclaw_vlm_monitor.pid}"

ssh_remote() {
  ssh \
    -F /dev/null \
    -o IdentitiesOnly=yes \
    -o StrictHostKeyChecking=no \
    -o UserKnownHostsFile=/dev/null \
    -o ProxyCommand="$PROXY_JUMP" \
    -i "$SSH_KEY" \
    "$SSH_TARGET" "$@"
}

snapshot_once() {
  local output
  output="$(ssh_remote bash -s <<'EOF'
set -euo pipefail
cd /workspace/YiFan/SpectrumClaw
log="$(ls -1t data/logs/multimodal_backfill_*.log 2>/dev/null | head -n 1 || true)"
if [ -z "$log" ]; then
  echo "timestamp=$(date '+%F %T')"
  echo "status=missing"
  echo "message=no_multimodal_backfill_log"
  exit 0
fi
pid_file="${log%.log}.pid"
pid=""
if [ -f "$pid_file" ]; then
  pid="$(cat "$pid_file" 2>/dev/null || true)"
fi
status="stopped"
if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
  status="running"
fi
echo "timestamp=$(date '+%F %T')"
echo "status=$status"
echo "log=$log"
echo "pid=${pid:-unknown}"
echo "--- tail ---"
tail -n 20 "$log" 2>/dev/null || true
EOF
)"
  printf '%s\n' "$output" | tee "$LATEST_FILE" | tee -a "$LOG_FILE"
}

monitor_loop() {
  trap 'rm -f "$PID_FILE"; exit 0' INT TERM
  echo "$$" > "$PID_FILE"
  while true; do
    snapshot_once
    sleep "$INTERVAL_SECONDS"
  done
}

status() {
  if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "[vlm-monitor] running pid=$(cat "$PID_FILE") interval=${INTERVAL_SECONDS}s"
  else
    echo "[vlm-monitor] stopped"
  fi
  if [ -f "$LATEST_FILE" ]; then
    echo "[vlm-monitor] latest snapshot:"
    cat "$LATEST_FILE"
  fi
}

stop() {
  if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    kill "$(cat "$PID_FILE")"
    rm -f "$PID_FILE"
  fi
  echo "[vlm-monitor] stopped"
}

case "${1:-daemon}" in
  once)
    snapshot_once
    ;;
  start)
    monitor_loop
    ;;
  daemon)
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      echo "[vlm-monitor] already running pid=$(cat "$PID_FILE")"
      exit 0
    fi
    setsid bash "$0" start > /dev/null 2>&1 < /dev/null &
    sleep 1
    status
    ;;
  status)
    status
    ;;
  stop)
    stop
    ;;
  *)
    echo "usage: $0 [once|start|daemon|status|stop]"
    exit 2
    ;;
esac
