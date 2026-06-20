#!/usr/bin/env bash
# SpectrumClaw 本地→3090 链路守护脚本
#
# 维护：
#   1) LLM forward proxy: 127.0.0.1:8240 → https://api.deepseek.com
#   2) SSH 双向隧道（autossh 自动重连）：
#      - 正向 0.0.0.0:8230 → 3090:8230  (浏览器/前端调后端 API)
#      - 反向 3090:8240   → 本地 8240   (3090 经本地代理调 deepseek)
#
# 用法：
#   scripts/local/start_links.sh           # 启动并守护（前台运行，Ctrl+C 退出）
#   scripts/local/start_links.sh stop      # 停掉所有相关进程
#   scripts/local/start_links.sh status    # 查看运行状态
#   scripts/local/start_links.sh daemon    # 后台启动，写 PID 到 /tmp/spectrumclaw_links.pid

set -uo pipefail

PROJECT_ROOT="/home/weiyifan/workspace/SpectrumClaw"
PROXY_SCRIPT="$PROJECT_ROOT/scripts/llm_forward_proxy.py"
PY="/home/weiyifan/miniconda3/envs/SpectrumClaw/bin/python"

# 3090 connection (via jump-27)
SSH_TARGET="root@162.18.1.4"
SSH_KEY="/home/weiyifan/.ssh/27_4000"
PROXY_JUMP="ssh -i $SSH_KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -W 162.18.1.4:22 jump-27"

# Ports
FORWARD_PORT=8230   # local → 3090 backend
PROXY_PORT=8240     # local proxy + reverse tunnel to 3090

PROXY_LOG="/tmp/spectrumclaw_proxy.log"
TUNNEL_LOG="/tmp/spectrumclaw_tunnel.log"
GUARD_PID_FILE="/tmp/spectrumclaw_links.pid"

# autossh monitor port — local TCP echo it uses to detect dead tunnels (0=disable)
export AUTOSSH_GATETIME=0           # don't bail on first failure
export AUTOSSH_POLL=30              # poll every 30s
export AUTOSSH_FIRST_POLL=10
export AUTOSSH_LOGFILE="$TUNNEL_LOG"
export AUTOSSH_DEBUG=0

start_proxy() {
  if pgrep -f "llm_forward_proxy.py" >/dev/null; then
    echo "[links] proxy already running"
    return
  fi
  echo "[links] starting LLM forward proxy on 127.0.0.1:$PROXY_PORT ..."
  setsid "$PY" -u "$PROXY_SCRIPT" > "$PROXY_LOG" 2>&1 < /dev/null &
  disown
  for i in $(seq 1 15); do
    if curl -s -m 2 "http://127.0.0.1:$PROXY_PORT/_proxy_health" >/dev/null 2>&1; then
      echo "[links] proxy up."
      return
    fi
    sleep 1
  done
  echo "[links] ERROR: proxy did not come up. See $PROXY_LOG"
  return 1
}

start_tunnel() {
  if pgrep -f "autossh.*$FORWARD_PORT:127.0.0.1:$FORWARD_PORT" >/dev/null; then
    echo "[links] tunnel already running"
    return
  fi
  echo "[links] starting autossh tunnel (-L $FORWARD_PORT, -R $PROXY_PORT) ..."
  # SSH_AUTH_SOCK lets us reuse vscode's ssh-agent
  SSH_AUTH_SOCK="${SSH_AUTH_SOCK:-/run/user/$(id -u)/vscode-ssh-auth-sock-592416355}" \
  setsid autossh -M 0 \
    -o ExitOnForwardFailure=yes \
    -o ServerAliveInterval=30 \
    -o ServerAliveCountMax=3 \
    -o StrictHostKeyChecking=no \
    -o UserKnownHostsFile=/dev/null \
    -o ProxyCommand="$PROXY_JUMP" \
    -i "$SSH_KEY" \
    -N \
    -L "0.0.0.0:$FORWARD_PORT:127.0.0.1:$FORWARD_PORT" \
    -R "$PROXY_PORT:127.0.0.1:$PROXY_PORT" \
    "$SSH_TARGET" \
    >> "$TUNNEL_LOG" 2>&1 < /dev/null &
  disown
  for i in $(seq 1 20); do
    if ss -tlnp 2>/dev/null | grep -q ":$FORWARD_PORT "; then
      echo "[links] tunnel up."
      return
    fi
    sleep 1
  done
  echo "[links] WARN: forward port $FORWARD_PORT did not come up in 20s. See $TUNNEL_LOG"
}

stop_all() {
  echo "[links] stopping ..."
  pkill -f "autossh.*$FORWARD_PORT:127.0.0.1:$FORWARD_PORT" 2>/dev/null
  pkill -f "ssh.*$FORWARD_PORT:127.0.0.1:$FORWARD_PORT" 2>/dev/null
  pkill -f "llm_forward_proxy.py" 2>/dev/null
  if [ -f "$GUARD_PID_FILE" ]; then
    kill "$(cat "$GUARD_PID_FILE")" 2>/dev/null
    rm -f "$GUARD_PID_FILE"
  fi
  sleep 1
  echo "[links] stopped."
}

status() {
  echo "[links] === ports ==="
  ss -tlnp 2>/dev/null | grep -E ":($FORWARD_PORT|$PROXY_PORT) " || echo "  (no listeners on $FORWARD_PORT/$PROXY_PORT)"
  echo "[links] === proxy ==="
  if pgrep -f llm_forward_proxy.py >/dev/null; then
    echo -n "  health: "; curl -s -m 3 "http://127.0.0.1:$PROXY_PORT/_proxy_health" 2>&1; echo
  else
    echo "  (down)"
  fi
  echo "[links] === tunnel ==="
  if pgrep -f "autossh.*$FORWARD_PORT" >/dev/null; then
    echo -n "  backend (8230): "
    curl -s -m 5 -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:$FORWARD_PORT/docs
  else
    echo "  (autossh down)"
  fi
  echo "[links] === guard ==="
  if [ -f "$GUARD_PID_FILE" ] && kill -0 "$(cat "$GUARD_PID_FILE")" 2>/dev/null; then
    echo "  guard PID $(cat "$GUARD_PID_FILE") running"
  else
    echo "  (no guard)"
  fi
}

guard_loop() {
  trap 'echo "[links] guard exiting ..."; stop_all; exit 0' INT TERM
  start_proxy
  start_tunnel
  echo "[links] guard loop started (PID $$). Ctrl+C to stop."
  while true; do
    if ! pgrep -f llm_forward_proxy.py >/dev/null; then
      echo "[links] proxy died — restarting"
      start_proxy
    fi
    if ! pgrep -f "autossh.*$FORWARD_PORT:127.0.0.1:$FORWARD_PORT" >/dev/null; then
      echo "[links] autossh died — restarting"
      start_tunnel
    fi
    sleep 15
  done
}

case "${1:-start}" in
  start)
    guard_loop
    ;;
  daemon)
    if [ -f "$GUARD_PID_FILE" ] && kill -0 "$(cat "$GUARD_PID_FILE")" 2>/dev/null; then
      echo "[links] guard already running (PID $(cat "$GUARD_PID_FILE"))"
      exit 0
    fi
    setsid bash "$0" start </dev/null > /tmp/spectrumclaw_guard.log 2>&1 &
    GUARD_PID=$!
    disown
    echo "$GUARD_PID" > "$GUARD_PID_FILE"
    sleep 4
    echo "[links] guard PID $GUARD_PID — log: /tmp/spectrumclaw_guard.log"
    status
    ;;
  stop)
    stop_all
    ;;
  status)
    status
    ;;
  *)
    echo "usage: $0 [start|daemon|stop|status]"
    exit 2
    ;;
esac
