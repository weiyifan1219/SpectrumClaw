#!/usr/bin/env bash
# Phase-1 bootstrap for the UAV Spectrum Simulation MVP.
# Safe to rerun: completed stages are marked under $SPECTRUMCLAW_RUNTIME_ROOT.

set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNTIME_ROOT="${SPECTRUMCLAW_RUNTIME_ROOT:-/workspace/YiFan/spectrumclaw_runtime}"
STATE_DIR="$RUNTIME_ROOT/install-state/uav-spectrum-sim-phase1"
LOG_DIR="$RUNTIME_ROOT/logs/uav-spectrum-sim-phase1"
PIP_CACHE_DIR="$RUNTIME_ROOT/cache/pip"
CONDA_BIN="${CONDA_BIN:-/root/miniconda3/bin/conda}"
PX4_DIR="$REPO_ROOT/simulation/third_party/PX4-Autopilot"
PX4_TAG="v1.17.0"
PROXY_URL="${UAV_SIM_PROXY_URL:-http://127.0.0.1:17897}"

mkdir -p "$STATE_DIR" "$LOG_DIR" "$PIP_CACHE_DIR"
exec 9>"$STATE_DIR/bootstrap.lock"
flock -n 9 || { echo "Another phase-1 bootstrap is already running." >&2; exit 1; }

export DEBIAN_FRONTEND=noninteractive
export http_proxy="$PROXY_URL"
export https_proxy="$PROXY_URL"
export HTTP_PROXY="$PROXY_URL"
export HTTPS_PROXY="$PROXY_URL"
export PIP_CACHE_DIR

log() { printf '[%s] %s\n' "$(date -Is)" "$*" | tee -a "$LOG_DIR/bootstrap.log"; }

retry() {
  local attempt=1 max_attempts=5 delay=5
  until "$@"; do
    if (( attempt >= max_attempts )); then
      return 1
    fi
    log "Command failed (attempt $attempt/$max_attempts); retrying in ${delay}s: $*"
    sleep "$delay"
    attempt=$((attempt + 1))
    delay=$((delay * 2))
  done
}

run_stage() {
  local name="$1"
  shift
  local marker="$STATE_DIR/${name}.done"
  if [[ -f "$marker" ]]; then
    log "Stage $name already complete; skipping."
    return
  fi
  log "Starting stage $name."
  "$@" 2>&1 | tee "$LOG_DIR/${name}.log"
  touch "$marker"
  log "Completed stage $name."
}

install_system() {
  retry apt-get update -o Acquire::Retries=5
  retry apt-get install -y --no-install-recommends \
    ca-certificates curl gnupg lsb-release software-properties-common \
    build-essential ccache cmake ninja-build pkg-config git python3-pip \
    python3-venv mesa-utils-extra
  add-apt-repository -y universe

  install -d -m 0755 /etc/apt/keyrings
  if [[ ! -f /usr/share/keyrings/ros-archive-keyring.gpg ]]; then
    retry curl -fsSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key \
      -o /usr/share/keyrings/ros-archive-keyring.gpg
  fi
  cat >/etc/apt/sources.list.d/ros2.list <<'EOF'
deb [arch=amd64 signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] http://packages.ros.org/ros2/ubuntu jammy main
EOF

  if [[ ! -f /usr/share/keyrings/pkgs-osrf-archive-keyring.gpg ]]; then
    retry curl -fsSL https://packages.osrfoundation.org/gazebo.gpg \
      -o /usr/share/keyrings/pkgs-osrf-archive-keyring.gpg
  fi
  cat >/etc/apt/sources.list.d/gazebo-stable.list <<'EOF'
deb [arch=amd64 signed-by=/usr/share/keyrings/pkgs-osrf-archive-keyring.gpg] https://packages.osrfoundation.org/gazebo/ubuntu-stable jammy main
EOF

  retry apt-get update -o Acquire::Retries=5
  retry apt-get install -y ros-humble-ros-base ros-dev-tools python3-rosdep gz-harmonic
  rosdep init 2>/dev/null || true
  rosdep update
}

install_px4() {
  # A previously interrupted upstream PX4 setup can leave an empty OSRF key.
  # Restore the verified key through the resumable reverse proxy before PX4
  # invokes apt for its remaining general build dependencies.
  retry curl -fsSL https://packages.osrfoundation.org/gazebo.gpg \
    -o /usr/share/keyrings/pkgs-osrf-archive-keyring.gpg
  chmod 0644 /usr/share/keyrings/pkgs-osrf-archive-keyring.gpg
  mkdir -p "$(dirname "$PX4_DIR")"
  if [[ ! -d "$PX4_DIR/.git" ]]; then
    if [[ -e "$PX4_DIR" ]]; then
      log "Removing incomplete non-Git PX4 directory: $PX4_DIR"
      rm -rf -- "$PX4_DIR"
    fi
    retry git clone --recursive --branch "$PX4_TAG" \
      https://github.com/PX4/PX4-Autopilot.git "$PX4_DIR"
  else
    git -C "$PX4_DIR" remote set-url origin https://github.com/PX4/PX4-Autopilot.git
    retry git -C "$PX4_DIR" fetch --tags --prune origin
    git -C "$PX4_DIR" checkout --detach "$PX4_TAG"
    retry git -C "$PX4_DIR" submodule update --init --recursive
  fi
  # Gazebo Harmonic is installed and version-controlled by install_system().
  # Skipping PX4's simulation setup prevents its sudo-wget path from bypassing
  # the reverse proxy and avoids replacing the pinned Gazebo repository.
  retry bash "$PX4_DIR/Tools/setup/ubuntu.sh" --no-nuttx --no-sim-tools
  git -C "$PX4_DIR" rev-parse HEAD >"$STATE_DIR/px4.commit"
}

install_sionna_rt() {
  if [[ ! -x "$CONDA_BIN" ]]; then
    echo "Conda not found at $CONDA_BIN" >&2
    return 1
  fi
  "$CONDA_BIN" config --set proxy_servers.http "$PROXY_URL"
  "$CONDA_BIN" config --set proxy_servers.https "$PROXY_URL"
  # Remove only the known stale local mirror, which bypasses proxy_servers and
  # is unavailable on the 3090 host after its old tunnel is gone.
  if "$CONDA_BIN" config --show-sources | grep -q '127\.0\.0\.1:8242'; then
    "$CONDA_BIN" config --remove-key default_channels || true
    "$CONDA_BIN" config --remove-key custom_channels || true
  fi
  if ! "$CONDA_BIN" env list | awk '{print $1}' | grep -qx 'spectrumclaw-rt'; then
    retry "$CONDA_BIN" create -y -n spectrumclaw-rt python=3.11 pip
  fi
  retry "$CONDA_BIN" run -n spectrumclaw-rt python -m pip install \
    --retries 12 --timeout 60 --prefer-binary 'sionna-rt==2.0.1'
}

source_ros_humble() {
  # ROS setup scripts reference optional variables that are legitimately unset.
  set +u
  source /opt/ros/humble/setup.bash
  set -u
}

verify_ros_gazebo_px4() {
  # PX4's gz_x500 optical-flow plugin needs OpenCV headers and CMake config.
  retry apt-get install -y --no-install-recommends libopencv-dev
  source_ros_humble
  ros2 --help >/dev/null
  gz sim --versions
  # Run the simulator in its own session.  Once startup is observed, terminate
  # that process group explicitly; `timeout make ...` alone can leave PX4/GZ
  # descendants behind on a headless machine.
  local smoke_log="$LOG_DIR/px4_gazebo_smoke.log"
  rm -f -- "$smoke_log"
  setsid env PX4_GZ_HEADLESS=1 HEADLESS=1 make -C "$PX4_DIR" px4_sitl gz_x500 \
    >"$smoke_log" 2>&1 &
  local smoke_pid=$!
  local observed=0
  for _ in $(seq 1 90); do
    if grep -Eq 'Gazebo world is ready|Startup script returned successfully' "$smoke_log"; then
      observed=1
      break
    fi
    if ! kill -0 "$smoke_pid" 2>/dev/null; then
      break
    fi
    sleep 2
  done
  kill -- -"$smoke_pid" 2>/dev/null || true
  wait "$smoke_pid" 2>/dev/null || true
  if [[ "$observed" -ne 1 ]]; then
    cat "$smoke_log" >&2
    return 1
  fi
}

verify_sionna_rt() {
  "$CONDA_BIN" run --no-capture-output -n spectrumclaw-rt env CUDA_VISIBLE_DEVICES=0 python - <<'PY'
import mitsuba as mi
import sionna.rt

mi.set_variant("cuda_ad_rgb")
variant = mi.variant()
assert variant.startswith("cuda"), f"Expected CUDA Mitsuba variant, got {variant!r}"
print("SIONNA_RT_SMOKE_OK", sionna.rt.__version__, variant)
PY
}

install_debug_bridge() {
  retry apt-get install -y ros-humble-foxglove-bridge
  source_ros_humble
  ros2 pkg prefix foxglove_bridge >/dev/null
}

write_versions_lock() {
  cat >"$STATE_DIR/versions.actual.txt" <<EOF
installed_at=$(date -Is)
os=$(source /etc/os-release && echo "$PRETTY_NAME")
ros=$(dpkg-query -W -f='${Version}' ros-humble-ros-base)
gazebo=$(gz sim --versions | tr '\n' ';')
px4_tag=$PX4_TAG
px4_commit=$(cat "$STATE_DIR/px4.commit")
sionna_rt=$($CONDA_BIN run -n spectrumclaw-rt python -c 'import sionna.rt; print(sionna.rt.__version__)')
EOF
}

main() {
  run_stage 01_system install_system
  run_stage 02_px4 install_px4
  run_stage 03_sionna_rt install_sionna_rt
  run_stage 04_ros_gazebo_px4_smoke verify_ros_gazebo_px4
  run_stage 05_sionna_rt_smoke verify_sionna_rt
  run_stage 06_versions write_versions_lock
  run_stage 07_debug_bridge install_debug_bridge
  log "Phase-1 environment bootstrap completed successfully."
}

main "$@"
