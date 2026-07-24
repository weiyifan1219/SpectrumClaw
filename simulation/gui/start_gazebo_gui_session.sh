#!/usr/bin/env bash
# Start an isolated native Gazebo GUI session for SpectrumClaw's embedded viewer.
#
# The GUI itself runs on the simulation server. x11vnc is intentionally bound to
# loopback only; browser access is relayed by the FastAPI WebSocket endpoint.
set -euo pipefail

runtime_root="${SPECTRUMCLAW_UAV_RUNTIME_ROOT:?SPECTRUMCLAW_UAV_RUNTIME_ROOT is required}"
px4_dir="${SPECTRUMCLAW_PX4_DIR:?SPECTRUMCLAW_PX4_DIR is required}"
display="${SPECTRUMCLAW_GAZEBO_GUI_DISPLAY:-:91}"
vnc_port="${SPECTRUMCLAW_GAZEBO_GUI_VNC_PORT:-5901}"
gz_env="${px4_dir}/build/px4_sitl_default/rootfs/gz_env.sh"
log_dir="${runtime_root}/logs/uav-spectrum-sim-phase1"

mkdir -p "${log_dir}"

for command in Xvfb x11vnc gz; do
  command -v "${command}" >/dev/null || {
    echo "missing required command: ${command}" >&2
    exit 1
  }
done
[[ -f "${gz_env}" ]] || { echo "missing PX4 Gazebo environment: ${gz_env}" >&2; exit 1; }

xvfb_pid=""
vnc_pid=""
gui_pid=""

cleanup() {
  for pid in "${gui_pid}" "${vnc_pid}" "${xvfb_pid}"; do
    if [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null; then
      kill "${pid}" 2>/dev/null || true
    fi
  done
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

Xvfb "${display}" -screen 0 1920x1080x24 -nolisten tcp +extension GLX +render -noreset \
  >>"${log_dir}/gazebo-gui.log" 2>&1 &
xvfb_pid=$!
sleep 1
kill -0 "${xvfb_pid}"

x11vnc -display "${display}" -rfbport "${vnc_port}" -localhost -forever -shared -nopw \
  -noxrecord -noxfixes -noxdamage >>"${log_dir}/gazebo-gui.log" 2>&1 &
vnc_pid=$!
sleep 1
kill -0 "${vnc_pid}"

set +u
source "${gz_env}"
set -u
export DISPLAY="${display}"
export GZ_IP="127.0.0.1"

gz sim -g >>"${log_dir}/gazebo-gui.log" 2>&1 &
gui_pid=$!

while kill -0 "${gui_pid}" 2>/dev/null && kill -0 "${vnc_pid}" 2>/dev/null; do
  sleep 1
done
