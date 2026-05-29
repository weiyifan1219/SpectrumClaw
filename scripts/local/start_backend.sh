#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."

conda run -n SpectrumClaw uvicorn backend.app:app --host 0.0.0.0 --port 8230 --reload
