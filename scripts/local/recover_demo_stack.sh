#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="/home/weiyifan/workspace/SpectrumClaw"
SSH_KEY="/home/weiyifan/.ssh/27_4000"
JUMP_HOST="172.18.101.27"
JUMP_PORT="4000"
SSH_TARGET="root@162.18.1.4"
REMOTE_PROJECT="/workspace/YiFan/SpectrumClaw"
FRONTEND_LOG="/tmp/spectrumclaw_frontend.log"

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

echo "[recover] 1/4 patch remote env and restart 3090 backend ..."
ssh_run "bash -lc '
  set -euo pipefail
  cd \"$REMOTE_PROJECT\"
  sed -i \"s#DEEPSEEK_BASE_URL=http://127.0.0.1:8240/v1#DEEPSEEK_BASE_URL=http://127.0.0.1:18240/v1#\" .env || true
  grep -E \"DEEPSEEK_BASE_URL|SPECTRUMCLAW_LLM_PROVIDER\" .env

  pgrep -f \"[u]vicorn backend.app:create_app .*--port 8230\" | xargs -r kill || true
  sleep 2

  if [ -x /root/miniconda3/bin/conda ]; then
    nohup /root/miniconda3/bin/conda run -n SpectrumClaw python -m uvicorn backend.app:create_app --factory --host 0.0.0.0 --port 8230 >/tmp/spectrumclaw_backend.log 2>&1 &
  elif [ -x /root/miniconda3/envs/SpectrumClaw/bin/python ]; then
    nohup /root/miniconda3/envs/SpectrumClaw/bin/python -m uvicorn backend.app:create_app --factory --host 0.0.0.0 --port 8230 >/tmp/spectrumclaw_backend.log 2>&1 &
  else
    nohup python -m uvicorn backend.app:create_app --factory --host 0.0.0.0 --port 8230 >/tmp/spectrumclaw_backend.log 2>&1 &
  fi

  sleep 5
  curl -fsS -m 10 http://127.0.0.1:8230/health
'"

echo "[recover] 2/4 restart local reverse links ..."
bash "$PROJECT_ROOT/scripts/local/start_links.sh" stop || true
bash "$PROJECT_ROOT/scripts/local/start_links.sh" daemon
sleep 3
curl -fsS -m 8 http://127.0.0.1:8230/health

echo "[recover] 3/4 restart local frontend on 5173 ..."
pkill -f "vite --host 127.0.0.1 --port 5173 --strictPort" || true
nohup bash "$PROJECT_ROOT/scripts/local/start_frontend.sh" >"$FRONTEND_LOG" 2>&1 &
sleep 4
curl -fsS -m 5 http://127.0.0.1:5173 >/dev/null

echo "[recover] 4/4 quick checks ..."
curl -fsS -m 8 http://127.0.0.1:8230/api/kb/stats | head -c 400
echo
echo "[recover] OK"
echo "[recover] frontend log: $FRONTEND_LOG"
echo "[recover] links log: /tmp/spectrumclaw_guard.log"
echo "[recover] backend log: /tmp/spectrumclaw_backend.log"
