#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../../frontend"
VITE_API_BASE="${VITE_API_BASE:-http://127.0.0.1:8230}" \
  npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
