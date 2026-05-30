"""Unified path constants for the RAG pipeline. Single source of truth."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# ── Data directories ──
DATA_DIR = PROJECT_ROOT / "data"
PARSED_DIR = DATA_DIR / "parsed"
CHROMA_DIR = DATA_DIR / "chroma"
GRAPH_DIR = DATA_DIR / "graph"
EVAL_DIR = DATA_DIR / "eval"
INDEX_DIR = DATA_DIR / "index"
UPLOADS_DIR = DATA_DIR / "uploads"
KB_RAW_DIR = DATA_DIR / "knowledge_base" / "raw"
KB_INDEX_DIR = DATA_DIR / "knowledge_base" / "index"

# ── Key files ──
GRAPH_PATH = GRAPH_DIR / "spectrum_graph.json"
DOC_REGISTRY_PATH = INDEX_DIR / "doc_registry.json"
CONFIG_PATH = PROJECT_ROOT / "config" / "rag.yaml"

# Ensure dirs exist
for d in [PARSED_DIR, CHROMA_DIR, GRAPH_DIR, EVAL_DIR, INDEX_DIR]:
    d.mkdir(parents=True, exist_ok=True)
