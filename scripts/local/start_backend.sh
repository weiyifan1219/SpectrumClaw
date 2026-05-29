#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."

# Allow AGENT_RUNTIME override via env var (default: legacy)
AGENT_RUNTIME="${SPECTRUMCLAW_AGENT_RUNTIME:-langgraph}"

echo "Starting SpectrumClaw backend with SPECTRUMCLAW_AGENT_RUNTIME=$AGENT_RUNTIME"

exec conda run --no-capture-output -n SpectrumClaw \
  env SPECTRUMCLAW_AGENT_RUNTIME="$AGENT_RUNTIME" \
  uvicorn backend.app:app --host 0.0.0.0 --port 8230 --reload
