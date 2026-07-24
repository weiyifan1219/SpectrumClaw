#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../../frontend"
VITE_HOST="${VITE_HOST:-0.0.0.0}"
VITE_API_BASE="${VITE_API_BASE:-/backend}" \
  VITE_HOST="$VITE_HOST" \
  npm run dev -- --host "$VITE_HOST" --port 5173 --strictPort
