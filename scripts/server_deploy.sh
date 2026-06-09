#!/bin/bash
# SpectrumClaw Server Deploy — run after extracting archive on server
# Usage: tar xzf spectrumclaw_server.tar.gz -C /root/ && cd /root/SpectrumClaw && bash scripts/server_deploy.sh

set -e

ENV_NAME="${1:-SpectrumClaw}"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="/usr/bin/python3"
CONDA_BIN="/root/miniconda3/bin/conda"

echo "=== SpectrumClaw Server Deploy ==="
echo "Python: $($PYTHON_BIN --version)"

# ── Step 1: Extract ITU documents zip if present ──
ITU_ZIP="$PROJECT_DIR/ITU_R_Documents.zip"
if [ -f "$ITU_ZIP" ]; then
    echo ""
    echo "=== Extracting ITU documents ==="
    mkdir -p "$PROJECT_DIR/data/knowledge_base/raw"
    $PYTHON_BIN -c "
import zipfile, os, sys
os.chdir(sys.argv[1])
with zipfile.ZipFile(sys.argv[2]) as z:
    z.extractall()
count = len([f for f in os.listdir('.') if f.endswith('.pdf')])
print(f'Extracted {count} PDFs')
" "$PROJECT_DIR/data/knowledge_base/raw" "$ITU_ZIP"
    echo "Done"
fi

# ── Step 2: Create Python environment ──
echo ""
echo "=== Creating Python environment: $ENV_NAME ==="
# Try conda first, fall back to venv
if "$CONDA_BIN" create -y -n "$ENV_NAME" python=3.10 pip --offline 2>/dev/null; then
    PIP_CMD="$CONDA_BIN run -n $ENV_NAME pip"
    echo "Conda env created: $ENV_NAME"
elif "$CONDA_BIN" create -y -n "$ENV_NAME" python=3.10 pip 2>/dev/null; then
    PIP_CMD="$CONDA_BIN run -n $ENV_NAME pip"
    echo "Conda env created (online): $ENV_NAME"
else
    echo "Conda not available, using venv..."
    $PYTHON_BIN -m venv "$PROJECT_DIR/venv"
    PIP_CMD="$PROJECT_DIR/venv/bin/pip"
    echo "Venv created at $PROJECT_DIR/venv"
fi

# ── Step 3: Install pip dependencies from wheelhouse ──
WHEELHOUSE="$PROJECT_DIR/wheelhouse"
if [ -d "$WHEELHOUSE" ]; then
    echo ""
    echo "=== Installing pip dependencies (offline) ==="
    $PIP_CMD install --no-index --find-links="$WHEELHOUSE" -r "$PROJECT_DIR/requirements-offline.txt"

    echo ""
    echo "=== Installing MinerU + Magic-PDF (offline) ==="
    $PIP_CMD install --no-index --find-links="$WHEELHOUSE" magic-pdf "mineru[core]==2.7.6"

    # Install opencv and rest
    $PIP_CMD install --no-index --find-links="$WHEELHOUSE" opencv-python-headless doclayout-yolo
else
    echo "ERROR: No wheelhouse found at $WHEELHOUSE"
    exit 1
fi

# ── Use conda run or direct Python ──
if [ "$PIP_CMD" != "${PIP_CMD#*conda}" ]; then
    PY_RUN="$CONDA_BIN run -n $ENV_NAME python3"
else
    PY_RUN="$PROJECT_DIR/venv/bin/python3"
fi

# ── Step 4: Set up environment ──
echo ""
echo "=== Setting up environment ==="
cd "$PROJECT_DIR"
if [ -f ".env.example" ] && [ ! -f ".env" ]; then
    cp .env.example .env
    echo "Created .env — please configure your API keys"
fi

# Create data directories
mkdir -p data/{knowledge_base/raw,chroma,graph,parsed,eval/reports,index,uploads}

# ── Step 5: Download MinerU models ──
echo ""
echo "=== Skipping MinerU model download (offline — download on server once connected) ==="
echo "To download models later: pip install modelscope && python3 -c \"from modelscope import snapshot_download; snapshot_download('opendatalab/PDF-Extract-Kit-1.0', cache_dir='/root/.cache/modelscope')\""

# Pre-load embedding model
echo ""
echo "=== Pre-loading sentence-transformers model ==="
$PY_RUN -c "
from sentence_transformers import SentenceTransformer
SentenceTransformer('all-MiniLM-L6-v2')
print('Embedding model cached')
"

# ── Step 6: Verify ──
echo ""
echo "=== Verification ==="
$PY_RUN -c "
import sys
sys.path.insert(0, '$PROJECT_DIR')
from backend.app import create_app
app = create_app()
print(f'App OK: {len(app.routes)} routes')
from backend.rag.parsers import ParserFactory
available = ParserFactory.list_available()
print(f'Available parsers: {available}')
print(f'MinerU ready: {\"mineru\" in available}')
"

echo ""
echo "=== Server deploy complete! ==="
echo ""
if [ "$PIP_CMD" != "${PIP_CMD#*conda}" ]; then
    echo "Run: conda activate $ENV_NAME"
    echo " or: $CONDA_BIN run -n $ENV_NAME uvicorn backend.app:create_app --factory --host 0.0.0.0 --port 8230"
else
    echo "Run: source $PROJECT_DIR/venv/bin/activate"
    echo " or: $PROJECT_DIR/venv/bin/uvicorn backend.app:create_app --factory --host 0.0.0.0 --port 8230"
fi
echo ""
echo "Index: $PY_RUN -m backend.rag.ingest --clear"
