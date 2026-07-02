#!/usr/bin/env bash
# SpectrumClaw 本地→3090 链路守护脚本
#
# 维护：
#   1) LLM forward proxy: 127.0.0.1:8240 → https://api.deepseek.com
#   2) SSH 双向隧道（autossh 自动重连）：
#      - 正向 127.0.0.1:8230 → 3090:8230   (浏览器/前端调后端 API)
#      - 反向 3090:18240     → 本地 8240   (3090 经本地代理调 deepseek)
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
JUMP_HOST="172.18.101.27"
JUMP_PORT="4000"
PROXY_JUMP="ssh -F /dev/null -i $SSH_KEY -p $JUMP_PORT -o IdentitiesOnly=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -W 162.18.1.4:22 root@$JUMP_HOST"

# Ports
FORWARD_PORT=8230        # local → 3090 backend
LOCAL_PROXY_PORT=8240    # local deepseek proxy
REMOTE_PROXY_PORT=18240  # remote reverse-tunnel endpoint for DeepSeek

PROXY_LOG="/tmp/spectrumclaw_proxy.log"
TUNNEL_LOG="/tmp/spectrumclaw_tunnel.log"
GUARD_PID_FILE="/tmp/spectrumclaw_links.pid"
GUARD_LOG="/tmp/spectrumclaw_guard.log"

# autossh monitor port — local TCP echo it uses to detect dead tunnels (0=disable)
export AUTOSSH_GATETIME=0           # don't bail on first failure
export AUTOSSH_POLL=30              # poll every 30s
export AUTOSSH_FIRST_POLL=10
export AUTOSSH_LOGFILE="$TUNNEL_LOG"
export AUTOSSH_DEBUG=0
STALE_REMOTE_NOTTY_SECONDS="${STALE_REMOTE_NOTTY_SECONDS:-90}"

tunnel_pattern() {
  echo "autossh.*$FORWARD_PORT:127.0.0.1:$FORWARD_PORT"
}

spawn_tunnel() {
  local mode="${1:-full}"
  local auth_sock="${SSH_AUTH_SOCK:-/run/user/$(id -u)/vscode-ssh-auth-sock-592416355}"
  local -a forwards=(
    -L "127.0.0.1:$FORWARD_PORT:127.0.0.1:$FORWARD_PORT"
  )
  if [ "$mode" = "full" ]; then
    forwards+=(-R "$REMOTE_PROXY_PORT:127.0.0.1:$LOCAL_PROXY_PORT")
  fi

  SSH_AUTH_SOCK="$auth_sock" \
  setsid autossh -M 0 \
    -F /dev/null \
    -o ExitOnForwardFailure=yes \
    -o ServerAliveInterval=30 \
    -o ServerAliveCountMax=3 \
    -o IdentitiesOnly=yes \
    -o StrictHostKeyChecking=no \
    -o UserKnownHostsFile=/dev/null \
    -o ProxyCommand="$PROXY_JUMP" \
    -i "$SSH_KEY" \
    -N \
    "${forwards[@]}" \
    "$SSH_TARGET" \
    >> "$TUNNEL_LOG" 2>&1 < /dev/null &
  disown
}

remote_exec() {
  ssh \
    -F /dev/null \
    -o IdentitiesOnly=yes \
    -o StrictHostKeyChecking=no \
    -o UserKnownHostsFile=/dev/null \
    -o ProxyCommand="$PROXY_JUMP" \
    -i "$SSH_KEY" \
    "$SSH_TARGET" "$@"
}

cleanup_remote_stale_notty() {
  echo "[links] cleaning stale remote sshd notty sessions (> ${STALE_REMOTE_NOTTY_SECONDS}s) ..."
  remote_exec "bash -lc '
    pids=\$(ps -eo pid=,etimes=,cmd= | awk '\''/sshd: root@notty/ && \$2 > ${STALE_REMOTE_NOTTY_SECONDS} {print \$1}'\'')
    if [ -n \"\$pids\" ]; then
      kill \$pids 2>/dev/null || true
      sleep 1
    fi
    ps -eo pid=,etimes=,cmd= | awk '\''/sshd: root@notty/ {print}'\'' || true
  '" || true
}

start_proxy() {
  if pgrep -f "llm_forward_proxy.py" >/dev/null; then
    echo "[links] proxy already running"
    return
  fi
  echo "[links] starting LLM forward proxy on 127.0.0.1:$LOCAL_PROXY_PORT ..."
  setsid "$PY" -u "$PROXY_SCRIPT" > "$PROXY_LOG" 2>&1 < /dev/null &
  disown
  for i in $(seq 1 15); do
    if curl -s -m 2 "http://127.0.0.1:$LOCAL_PROXY_PORT/_proxy_health" >/dev/null 2>&1; then
      echo "[links] proxy up."
      return
    fi
    sleep 1
  done
  echo "[links] ERROR: proxy did not come up. See $PROXY_LOG"
  return 1
}

start_tunnel() {
  if pgrep -f "$(tunnel_pattern)" >/dev/null; then
    echo "[links] tunnel already running"
    return
  fi
  echo "[links] starting autossh tunnel (-L $FORWARD_PORT, -R $REMOTE_PROXY_PORT -> $LOCAL_PROXY_PORT) ..."
  cleanup_remote_stale_notty
  : > "$TUNNEL_LOG"
  spawn_tunnel full
  for i in $(seq 1 10); do
    if grep -q "remote port forwarding failed for listen port $REMOTE_PROXY_PORT" "$TUNNEL_LOG" 2>/dev/null; then
      echo "[links] remote reverse port $REMOTE_PROXY_PORT busy — falling back to forward-only tunnel"
      pkill -f "$(tunnel_pattern)" 2>/dev/null || true
      sleep 1
      : > "$TUNNEL_LOG"
      spawn_tunnel forward-only
      break
    fi
    if ss -tlnp 2>/dev/null | grep -q ":$FORWARD_PORT "; then
      echo "[links] tunnel up."
      return
    fi
    sleep 1
  done
  for i in $(seq 1 10); do
    if ss -tlnp 2>/dev/null | grep -q ":$FORWARD_PORT "; then
      echo "[links] forward-only tunnel up."
      return
    fi
    sleep 1
  done
  echo "[links] WARN: forward port $FORWARD_PORT did not come up. See $TUNNEL_LOG"
}

stop_all() {
  echo "[links] stopping ..."
  pkill -f "$(tunnel_pattern)" 2>/dev/null
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
  ss -tlnp 2>/dev/null | grep -E ":($FORWARD_PORT|$LOCAL_PROXY_PORT) " || echo "  (no listeners on $FORWARD_PORT/$LOCAL_PROXY_PORT)"
  echo "[links] === proxy ==="
  if pgrep -f llm_forward_proxy.py >/dev/null; then
    echo -n "  health: "; curl -s -m 3 "http://127.0.0.1:$LOCAL_PROXY_PORT/_proxy_health" 2>&1; echo
  else
    echo "  (down)"
  fi
  echo "[links] === tunnel ==="
  if pgrep -f "$(tunnel_pattern)" >/dev/null; then
    echo -n "  backend (8230): "
    curl -s -m 5 -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:$FORWARD_PORT/docs
  else
    echo "  (autossh down)"
  fi
  echo "[links] === guard ==="
  if [ -f "$GUARD_PID_FILE" ] && kill -0 "$(cat "$GUARD_PID_FILE")" 2>/dev/null; then
    echo "  guard PID $(cat "$GUARD_PID_FILE") running (log: $GUARD_LOG)"
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
    if ! pgrep -f "$(tunnel_pattern)" >/dev/null; then
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
    nohup bash "$0" start > "$GUARD_LOG" 2>&1 < /dev/null &
    GUARD_PID=$!
    echo "$GUARD_PID" > "$GUARD_PID_FILE"
    sleep 4
    echo "[links] guard PID $GUARD_PID — log: $GUARD_LOG"
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
