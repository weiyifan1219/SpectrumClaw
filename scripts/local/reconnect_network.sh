#!/usr/bin/env bash
set -euo pipefail

wait_for_url() {
  local url="$1"
  local attempts="${2:-40}"
  for _ in $(seq 1 "$attempts"); do
    if curl -fsS -m 4 "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  echo "[network] timeout waiting for $url" >&2
  return 1
}

echo "[network] restarting server backend link ..."
systemctl --user restart spectrumclaw-links.service

wait_for_url http://127.0.0.1:8230/health

LOCAL_IP="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '
  /src/ { for (i = 1; i <= NF; i++) if ($i == "src") { print $(i + 1); exit } }
')"
if [ -z "$LOCAL_IP" ]; then
  LOCAL_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
fi

echo "[network] server-hosted frontend is ready"
echo "[network] local loopback URL: http://127.0.0.1:8230/"
if [ -n "$LOCAL_IP" ]; then
  echo "[network] browser URL:      http://$LOCAL_IP:8230/"
fi
echo "[network] server URL (only when network ACL allows it): http://162.18.1.4:8230/"
if [ -n "$LOCAL_IP" ]; then
  echo "[network] current local IP: $LOCAL_IP (仅用于本地链路，不是页面地址)"
fi
echo "[network] browser no longer depends on local Vite or local port 5173"
