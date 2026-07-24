#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="/home/weiyifan/workspace/SpectrumClaw"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
ENABLE_LOCAL_FRONTEND="${ENABLE_LOCAL_FRONTEND:-0}"

if ! systemctl --user is-system-running >/dev/null 2>&1; then
  echo "[services] user systemd is not available" >&2
  exit 1
fi

mkdir -p "$UNIT_DIR"
install -m 0644 \
  "$PROJECT_ROOT/scripts/local/systemd/spectrumclaw-links.service" \
  "$UNIT_DIR/spectrumclaw-links.service"
install -m 0644 \
  "$PROJECT_ROOT/scripts/local/systemd/spectrumclaw-frontend.service" \
  "$UNIT_DIR/spectrumclaw-frontend.service"
install -m 0644 \
  "$PROJECT_ROOT/scripts/local/systemd/spectrumclaw-network-watchdog.service" \
  "$UNIT_DIR/spectrumclaw-network-watchdog.service"

systemctl --user daemon-reload
systemctl --user enable --now spectrumclaw-links.service spectrumclaw-network-watchdog.service

if [ "$ENABLE_LOCAL_FRONTEND" = "1" ]; then
  systemctl --user enable --now spectrumclaw-frontend.service
else
  systemctl --user disable --now spectrumclaw-frontend.service >/dev/null 2>&1 || true
fi
echo "[services] installed user services in $UNIT_DIR"
if [ "$ENABLE_LOCAL_FRONTEND" = "1" ]; then
  echo "[services] optional local Vite frontend is enabled"
else
  echo "[services] server-hosted frontend mode; use ENABLE_LOCAL_FRONTEND=1 only for local development"
fi
