#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="/home/weiyifan/workspace/SpectrumClaw"
SSH_KEY="/home/weiyifan/.ssh/27_4000"
JUMP_HOST="172.18.101.27"
JUMP_PORT="4000"
SSH_TARGET="root@162.18.1.4"
REMOTE_PROJECT="/workspace/YiFan/SpectrumClaw"
FRONTEND_LOG="/tmp/spectrumclaw_frontend.log"

wait_for_http() {
  local url="$1"
  local attempts="${2:-60}"
  for _ in $(seq 1 "$attempts"); do
    if curl -fsS -m 5 "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  echo "[recover] timeout waiting for $url" >&2
  return 1
}

ssh_run() {
  ssh \
    -F /dev/null \
    -o IdentitiesOnly=yes \
    -o StrictHostKeyChecking=no \
    -o UserKnownHostsFile=/dev/null \
    -o ProxyCommand="ssh -F /dev/null -i $SSH_KEY -p $JUMP_PORT -o IdentitiesOnly=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -W 162.18.1.4:22 root@$JUMP_HOST" \
    -i "$SSH_KEY" \
    "$SSH_TARGET" "$@"
}

scp_run() {
  scp -q \
    -F /dev/null \
    -o IdentitiesOnly=yes \
    -o StrictHostKeyChecking=no \
    -o UserKnownHostsFile=/dev/null \
    -o ProxyCommand="ssh -F /dev/null -i $SSH_KEY -p $JUMP_PORT -o IdentitiesOnly=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -W 162.18.1.4:22 root@$JUMP_HOST" \
    -i "$SSH_KEY" \
    "$PROJECT_ROOT/scripts/server_backend_guard.sh" \
    "$SSH_TARGET:$REMOTE_PROJECT/scripts/server_backend_guard.sh"
}

echo "[recover] 1/4 patch remote env and restart 3090 backend ..."
scp_run
ssh_run "bash -lc '
  set -euo pipefail
  cd \"$REMOTE_PROJECT\"
  sed -i \"s#DEEPSEEK_BASE_URL=http://127.0.0.1:8240/v1#DEEPSEEK_BASE_URL=http://127.0.0.1:18240/v1#\" .env || true
  grep -E \"DEEPSEEK_BASE_URL|SPECTRUMCLAW_LLM_PROVIDER\" .env

  guard_pid=/tmp/spectrumclaw_backend_guard.pid
  if [ -f \"\$guard_pid\" ]; then
    kill \"\$(cat \"\$guard_pid\")\" 2>/dev/null || true
    rm -f \"\$guard_pid\"
  fi
  pgrep -f \"[u]vicorn backend.app:create_app .*--port 8230\" | xargs -r kill || true
  pgrep -f \"[c]onda run -n SpectrumClaw.*--port 8230\" | xargs -r kill || true

  setsid bash \"$REMOTE_PROJECT/scripts/server_backend_guard.sh\" </dev/null >/tmp/spectrumclaw_backend_guard.log 2>&1 &
  echo \$! > \"\$guard_pid\"
  for i in \$(seq 1 60); do
    if curl -fsS -m 5 http://127.0.0.1:8230/health; then
      echo
      break
    fi
    sleep 1
  done
  curl -fsS -m 10 http://127.0.0.1:8230/health
'"

echo "[recover] 2/4 restart local reverse links ..."
if systemctl --user cat spectrumclaw-links.service >/dev/null 2>&1; then
  systemctl --user restart spectrumclaw-links.service
else
  bash "$PROJECT_ROOT/scripts/local/start_links.sh" stop || true
  bash "$PROJECT_ROOT/scripts/local/start_links.sh" daemon
fi
wait_for_http http://127.0.0.1:8230/health

echo "[recover] 3/4 restart local frontend on 5173 ..."
if systemctl --user cat spectrumclaw-frontend.service >/dev/null 2>&1; then
  systemctl --user restart spectrumclaw-frontend.service
else
  setsid bash "$PROJECT_ROOT/scripts/local/start_frontend.sh" >"$FRONTEND_LOG" 2>&1 </dev/null &
fi
wait_for_http http://127.0.0.1:5173

echo "[recover] 4/4 quick checks ..."
curl -fsS -m 8 http://127.0.0.1:8230/api/kb/stats | head -c 400
echo
echo "[recover] OK"
echo "[recover] frontend log: $FRONTEND_LOG"
echo "[recover] links log: /tmp/spectrumclaw_guard.log"
echo "[recover] backend log: /tmp/spectrumclaw_backend.log"
