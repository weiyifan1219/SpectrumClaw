#!/usr/bin/env bash
# Bring up the offline-LLM bridge for the 3090 server:
#   local forward proxy (127.0.0.1:8240 -> api.deepseek.com)
#   + SSH reverse tunnel (server 127.0.0.1:8240 -> local 8240)
#
# Idempotent: re-running kills stale instances and restarts cleanly.
#
# Usage:
#   scripts/local/start_llm_bridge.sh          # start both, verify
#   scripts/local/start_llm_bridge.sh status   # show status only
#   scripts/local/start_llm_bridge.sh stop      # tear down both
set -uo pipefail

PROJECT_ROOT="/home/lenovo/workspace/SpectrumClaw"
PY="/home/lenovo/miniconda3/envs/SpectrumClaw/bin/python"
PROXY_SCRIPT="$PROJECT_ROOT/scripts/llm_forward_proxy.py"
SERVER="weiyifan3090"
PORT=8240
PROXY_LOG="/tmp/llm_proxy.log"
TUNNEL_LOG="/tmp/llm_tunnel.log"

proxy_pids() { pgrep -f "llm_forward_proxy.py"; }
tunnel_pids() { pgrep -f "ssh -N -R ${PORT}:127.0.0.1:${PORT}"; }

stop_all() {
  echo "[bridge] stopping proxy + tunnel ..."
  pkill -f "llm_forward_proxy.py" 2>/dev/null
  pkill -f "ssh -N -R ${PORT}:127.0.0.1:${PORT}" 2>/dev/null
  sleep 1
  echo "[bridge] stopped."
}

status() {
  local p t
  p=$(proxy_pids | tr '\n' ' ')
  t=$(tunnel_pids | tr '\n' ' ')
  echo "[bridge] proxy  pid: ${p:-<none>}"
  echo "[bridge] tunnel pid: ${t:-<none>}"
  echo -n "[bridge] local  proxy health: "
  curl -s -m 5 "http://127.0.0.1:${PORT}/_proxy_health" 2>/dev/null || echo "(unreachable)"
  echo ""
  echo -n "[bridge] server via tunnel:    "
  ssh "$SERVER" "curl -s -m 6 http://127.0.0.1:${PORT}/_proxy_health" </dev/null 2>/dev/null || echo "(unreachable)"
  echo ""
}

case "${1:-start}" in
  stop)   stop_all; exit 0 ;;
  status) status; exit 0 ;;
esac

# ── start ──
stop_all

echo "[bridge] starting local forward proxy on 127.0.0.1:${PORT} ..."
setsid "$PY" -u "$PROXY_SCRIPT" > "$PROXY_LOG" 2>&1 < /dev/null &
disown

# wait for proxy to answer health
for i in $(seq 1 15); do
  if curl -s -m 3 "http://127.0.0.1:${PORT}/_proxy_health" >/dev/null 2>&1; then
    echo "[bridge] proxy up."
    break
  fi
  sleep 1
  if [ "$i" = 15 ]; then
    echo "[bridge] ERROR: proxy did not come up. Log:"; tail -20 "$PROXY_LOG"; exit 1
  fi
done

echo "[bridge] starting SSH reverse tunnel (${SERVER}: 127.0.0.1:${PORT} -> local ${PORT}) ..."
setsid ssh -N -R "${PORT}:127.0.0.1:${PORT}" \
  -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
  "$SERVER" > "$TUNNEL_LOG" 2>&1 < /dev/null &
disown
sleep 3

echo ""
status

# final end-to-end check
if ssh "$SERVER" "curl -s -m 8 http://127.0.0.1:${PORT}/v1/models -H 'Authorization: Bearer '\$(grep '^DEEPSEEK_API_KEY=' /workspace/YiFan/SpectrumClaw/.env | cut -d= -f2)" </dev/null 2>/dev/null | grep -q '"object"'; then
  echo "[bridge] OK — server can reach deepseek through the bridge."
else
  echo "[bridge] WARN — end-to-end model check did not confirm. Check logs: $PROXY_LOG / $TUNNEL_LOG"
fi
