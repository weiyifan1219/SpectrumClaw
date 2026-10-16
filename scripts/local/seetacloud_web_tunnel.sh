#!/usr/bin/env bash
# Run on the user's computer; keep one stable browser URL across reconnects.
set -uo pipefail

SSH_TARGET="${SPECTRUMCLAW_SSH_TARGET:-seetacloud-bjb1}"
LOCAL_PORT=8230
REMOTE_PORT=8230

if command -v python3 >/dev/null 2>&1; then
  if ! python3 - "$LOCAL_PORT" <<'PY'
import socket
import sys

with socket.socket() as sock:
    try:
        sock.bind(("127.0.0.1", int(sys.argv[1])))
    except OSError:
        raise SystemExit(1)
PY
  then
    echo "本机 8230 已被占用。请关闭旧隧道或占用该端口的程序；此脚本不会改用其他端口。" >&2
    exit 1
  fi
fi

echo "固定网页地址：http://127.0.0.1:${LOCAL_PORT}/#uav_spectrum_sim"
echo "连接 ${SSH_TARGET}；断线后会继续在同一端口重连。按 Ctrl+C 停止。"
trap 'exit 0' INT TERM

while true; do
  ssh -N -T \
    -L "127.0.0.1:${LOCAL_PORT}:127.0.0.1:${REMOTE_PORT}" \
    -o ExitOnForwardFailure=yes \
    -o ServerAliveInterval=15 \
    -o ServerAliveCountMax=3 \
    -o ConnectTimeout=10 \
    "$SSH_TARGET"
  exit_code=$?
  if (( exit_code == 0 )); then exit 0; fi
  if command -v python3 >/dev/null 2>&1 && ! python3 - "$LOCAL_PORT" <<'PY'
import socket
import sys

with socket.socket() as sock:
    try:
        sock.bind(("127.0.0.1", int(sys.argv[1])))
    except OSError:
        raise SystemExit(1)
PY
  then
    echo "本机 8230 已被其他程序占用；停止重连，避免打开错误的网页。" >&2
    exit 1
  fi
  echo "隧道已断开（状态 ${exit_code}），3 秒后重连 ${SSH_TARGET}，本地端口保持 ${LOCAL_PORT}。" >&2
  sleep 3
done
