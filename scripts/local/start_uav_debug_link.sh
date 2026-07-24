#!/usr/bin/env bash
# Starts a private Foxglove WebSocket path: local 127.0.0.1:8765 -> 3090.
# The server binds only to its loopback interface and is never exposed publicly.

set -Eeuo pipefail

REMOTE_HOST="${UAV_SIM_REMOTE_HOST:-weiyifan3090}"
REMOTE_PORT="${UAV_SIM_FOXGLOVE_PORT:-8765}"
LOCAL_PORT="${UAV_SIM_LOCAL_PORT:-8765}"

ssh -o BatchMode=yes -o ConnectTimeout=15 "$REMOTE_HOST" \
  "mkdir -p /workspace/YiFan/spectrumclaw_runtime/logs/uav-spectrum-sim-phase1
   if ! python3 -c 'import socket; socket.create_connection((\"127.0.0.1\", $REMOTE_PORT), 1)' 2>/dev/null; then
     nohup bash -lc 'source /opt/ros/humble/setup.bash && ros2 launch foxglove_bridge foxglove_bridge_launch.xml address:=127.0.0.1 port:=$REMOTE_PORT' \
       >/workspace/YiFan/spectrumclaw_runtime/logs/uav-spectrum-sim-phase1/foxglove_bridge.log 2>&1 < /dev/null &
   fi"

exec autossh -M 0 -N \
  -o BatchMode=yes \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -L "127.0.0.1:${LOCAL_PORT}:127.0.0.1:${REMOTE_PORT}" "$REMOTE_HOST"
