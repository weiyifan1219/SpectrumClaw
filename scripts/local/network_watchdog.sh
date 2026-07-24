#!/usr/bin/env bash
set -u

PROJECT_ROOT="/home/weiyifan/workspace/SpectrumClaw"
RECONNECT_SCRIPT="$PROJECT_ROOT/scripts/local/reconnect_network.sh"
LOG_FILE="/tmp/spectrumclaw_network_watchdog.log"

if ! command -v ip >/dev/null 2>&1; then
  echo "[network-watchdog] ip command is unavailable" >&2
  exit 1
fi

network_signature() {
  {
    ip -4 -o addr show scope global 2>/dev/null | awk '{print $2, $4}' || true
    ip -4 route show default 2>/dev/null || true
  } | sort
}

is_relevant_event() {
  case "$1" in
    *inet6*|*mngtmpaddr*) return 1 ;;
    *"inet "*|*"default "*|*"state UP"*|*"state DOWN"*|*LOWER_UP*|*NO-CARRIER*) return 0 ;;
    *) return 1 ;;
  esac
}

run_reconnect() {
  echo "[$(date -Is)] network event received; reconnecting" >> "$LOG_FILE"
  if "$RECONNECT_SCRIPT" >> "$LOG_FILE" 2>&1; then
    echo "[$(date -Is)] reconnect completed" >> "$LOG_FILE"
  else
    echo "[$(date -Is)] reconnect failed; waiting for the next network event" >> "$LOG_FILE"
  fi
}

# Establish a known-good state when the service starts, then wait for kernel
# network events instead of polling health endpoints on a timer.
last_signature="$(network_signature)"
run_reconnect || true

while IFS= read -r event; do
  [ -n "$event" ] || continue
  if ! is_relevant_event "$event"; then
    continue
  fi
  echo "[$(date -Is)] event: $event" >> "$LOG_FILE"

  # NetworkManager and DHCP commonly emit several events for one transition.
  # Debounce that burst, then drain any additional events before reconnecting.
  sleep 2
  while IFS= read -r -t 1 _; do :; done

  new_signature="$(network_signature)"
  if [ "$new_signature" = "$last_signature" ]; then
    echo "[$(date -Is)] relevant event did not change IPv4 network; skipping reconnect" >> "$LOG_FILE"
    continue
  fi
  last_signature="$new_signature"
  run_reconnect
done < <(ip monitor address route link)
