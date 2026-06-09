#!/bin/bash
# SpectrumClaw Server Setup — offline install
# Run: bash scripts/setup_server.sh

set -e

ENV_NAME="${1:-SpectrumClaw}"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "=== SpectrumClaw Server Setup ==="
echo "Environment: $ENV_NAME"
echo "Project dir: $PROJECT_DIR"

# ── Step 1: Create conda environment ──
echo ""
echo "=== Creating conda environment: $ENV_NAME ==="
conda create -y -n "$ENV_NAME" python=3.11 pip
source activate "$ENV_NAME" 2>/dev/null || conda activate "$ENV_NAME"

# ── Step 2: Install pip dependencies from wheelhouse ──
WHEELHOUSE="$PROJECT_DIR/wheelhouse"
if [ -d "$WHEELHOUSE" ] && [ "$(ls -A "$WHEELHOUSE")" ]; then
    echo ""
    echo "=== Installing dependencies from wheelhouse (offline) ==="
    pip install --no-index --find-links="$WHEELHOUSE" -r "$PROJECT_DIR/requirements.txt"
else
    echo ""
    echo "=== No wheelhouse found. Attempting online install ==="
    pip install -r "$PROJECT_DIR/requirements.txt"
fi

# ── Step 3: Download MinerU models ──
echo ""
echo "=== Downloading MinerU models ==="
pip install mineru[core] magic-pdf
pip install opencv-python-headless doclayout-yolo
# Download models from huggingface (server may have internet after all)
mineru --help >/dev/null 2>&1 && echo "MinerU installed" || echo "MinerU not available via CLI"

# ── Step 4: Download sentence-transformers model ──
echo ""
echo "=== Pre-downloading sentence-transformers model ==="
python3 -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')" || true

# ── Step 5: Set up environment ──
echo ""
echo "=== Setting up environment ==="
if [ -f "$PROJECT_DIR/.env.example" ] && [ ! -f "$PROJECT_DIR/.env" ]; then
    cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
    echo "Created .env from .env.example — please configure your API keys"
fi

# Create data directories
mkdir -p "$PROJECT_DIR"/data/{knowledge_base/raw,chroma,graph,parsed,eval/reports,index,uploads}

# ── Step 6: Verify ──
echo ""
echo "=== Verification ==="
python3 -c "
from backend.app import create_app
app = create_app()
print(f'App OK: {len(app.routes)} routes')

from backend.rag.parsers import ParserFactory
available = ParserFactory.list_available()
print(f'Available parsers: {available}')
print(f'MinerU available: {\"mineru\" in available}')
"

echo ""
echo "=== Setup complete ==="
echo "Start the server: uvicorn backend.app:create_app --factory --host 0.0.0.0 --port 8230"
echo "Or with GPU: uvicorn backend.app:create_app --factory --host 0.0.0.0 --port 8230"
echo ""
echo "To index ITU documents with MinerU:"
echo "  python -m backend.rag.ingest --clear"
echo "  (or use pypdf fallback: SPECTRUMCLAW_PARSER=pypdf python -m backend.rag.ingest --clear)"
