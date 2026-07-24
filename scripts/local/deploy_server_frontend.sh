#!/usr/bin/env bash
set -euo pipefail

# Build the frontend as a same-origin production bundle and publish it beside
# the backend. After deployment, open http://<server-ip>:8230/ directly.

PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SSH_KEY="${SSH_KEY:-/home/weiyifan/.ssh/27_4000}"
JUMP_HOST="${JUMP_HOST:-172.18.101.27}"
JUMP_PORT="${JUMP_PORT:-4000}"
REMOTE_HOST="${REMOTE_HOST:-162.18.1.4}"
SSH_TARGET="${SSH_TARGET:-root@$REMOTE_HOST}"
REMOTE_PROJECT="${REMOTE_PROJECT:-/workspace/YiFan/SpectrumClaw}"

PROXY_COMMAND="ssh -F /dev/null -i $SSH_KEY -p $JUMP_PORT -o IdentitiesOnly=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -W $REMOTE_HOST:22 root@$JUMP_HOST"
SSH_OPTS=(
  -F /dev/null
  -i "$SSH_KEY"
  -o IdentitiesOnly=yes
  -o StrictHostKeyChecking=no
  -o UserKnownHostsFile=/dev/null
  -o "ProxyCommand=$PROXY_COMMAND"
)

ssh_run() {
  ssh "${SSH_OPTS[@]}" "$SSH_TARGET" "$@"
}

scp_run() {
  scp "${SSH_OPTS[@]}" "$@"
}

echo "[server-frontend] building same-origin frontend ..."
cd "$PROJECT_ROOT"
VITE_API_BASE="" npm --prefix frontend run build

DIST_DIR="$PROJECT_ROOT/frontend/dist"
test -f "$DIST_DIR/index.html"

DEPLOY_ID="$(date +%s)"
REMOTE_DIST_NEXT="$REMOTE_PROJECT/frontend/.dist.next.$DEPLOY_ID"
REMOTE_APP_NEXT="$REMOTE_PROJECT/backend/app.py.next.$DEPLOY_ID"

echo "[server-frontend] uploading backend app and frontend bundle ..."
scp_run "$PROJECT_ROOT/backend/app.py" "$SSH_TARGET:$REMOTE_APP_NEXT"
scp_run -r "$DIST_DIR" "$SSH_TARGET:$REMOTE_DIST_NEXT"

ssh_run "bash -s" <<EOF
set -euo pipefail
cd "$REMOTE_PROJECT"
test -f "$REMOTE_APP_NEXT"
test -f "$REMOTE_DIST_NEXT/index.html"
mv "$REMOTE_APP_NEXT" backend/app.py
rm -rf frontend/dist
mv "$REMOTE_DIST_NEXT" frontend/dist
EOF

echo "[server-frontend] restarting remote backend ..."
ssh_run "bash -s" <<EOF
set -euo pipefail
cd "$REMOTE_PROJECT"
guard_pid=/tmp/spectrumclaw_backend_guard.pid
if [ -f "\$guard_pid" ]; then
  kill "\$(cat "\$guard_pid")" 2>/dev/null || true
  rm -f "\$guard_pid"
fi
for _ in \$(seq 1 20); do
  if ! pgrep -f '[u]vicorn backend.app:create_app .*--port 8230' >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
pgrep -f '[u]vicorn backend.app:create_app .*--port 8230' | xargs -r kill || true
setsid bash "$REMOTE_PROJECT/scripts/server_backend_guard.sh" </dev/null >/tmp/spectrumclaw_backend_guard.log 2>&1 &
echo \$! > "\$guard_pid"
for _ in \$(seq 1 60); do
  if curl -fsS -m 5 http://127.0.0.1:8230/health >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
curl -fsS -m 10 http://127.0.0.1:8230/health
echo
curl -fsS -m 10 http://127.0.0.1:8230/ | head -c 120
echo
EOF

echo "[server-frontend] deployed"
echo "[server-frontend] open: http://$REMOTE_HOST:8230/"
