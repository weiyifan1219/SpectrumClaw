"""PDF ingestion pipeline: extract text → chunk → index with TF-IDF → store in sqlite."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import zipfile
from pathlib import Path

import numpy as np
from pypdf import PdfReader
from sklearn.feature_extraction.text import TfidfVectorizer

PROJECT_ROOT = Path(__file__).resolve().parents[2]
KB_DIR = PROJECT_ROOT / "data" / "knowledge_base"
ZIP_PATH = PROJECT_ROOT / "itu_documents.zip"
EXTRACT_DIR = KB_DIR / "raw"
DB_PATH = KB_DIR / "kb.sqlite3"
INDEX_DIR = KB_DIR / "index"

CHUNK_MIN_CHARS = 60
CHUNK_MAX_CHARS = 2000


def _clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _extract_pdf_text(path: Path) -> str:
    reader = PdfReader(str(path))
    parts: list[str] = []
    for page in reader.pages:
        t = page.extract_text()
        if t:
            parts.append(t)
    return "\n".join(parts)


def _chunk_text(text: str, source: str) -> list[dict]:
    """Split text into paragraph-based chunks."""
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    chunks = []
    buf = ""
    for para in paragraphs:
        if buf and len(buf) + len(para) > CHUNK_MAX_CHARS:
            c = _clean_text(buf)
            if len(c) >= CHUNK_MIN_CHARS:
                chunks.append({"text": c, "source": source})
            buf = para
        else:
            buf = f"{buf}\n{para}" if buf else para
    if buf:
        c = _clean_text(buf)
        if len(c) >= CHUNK_MIN_CHARS:
            chunks.append({"text": c, "source": source})
    return chunks


def _build_index(chunks: list[dict]) -> tuple[np.ndarray, np.ndarray, TfidfVectorizer]:
    """Build TF-IDF sparse matrix from chunks."""
    texts = [c["text"] for c in chunks]
    vectorizer = TfidfVectorizer(
        max_features=10000,
        ngram_range=(1, 2),
        stop_words=None,
    )
    matrix = vectorizer.fit_transform(texts)
    return matrix, np.array([c["source"] for c in chunks]), vectorizer


def ingest() -> dict:
    """Run full ingestion pipeline. Returns summary dict."""
    KB_DIR.mkdir(parents=True, exist_ok=True)
    EXTRACT_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Extract PDFs (skip .gitkeep and other non-PDF files)
    pdf_files = sorted(EXTRACT_DIR.rglob("*.pdf"))
    if not pdf_files:
        print(f"Extracting {ZIP_PATH} → {EXTRACT_DIR} ...")
        with zipfile.ZipFile(ZIP_PATH) as zf:
            pdf_names = [n for n in zf.namelist() if n.lower().endswith(".pdf")]
            for name in pdf_names:
                zf.extract(name, EXTRACT_DIR)
        print(f"Extracted {len(pdf_names)} PDFs")
        pdf_files = sorted(EXTRACT_DIR.rglob("*.pdf"))
    print(f"Found {len(pdf_files)} PDFs")

    # 2. Extract text + chunk
    all_chunks: list[dict] = []
    for pdf_path in pdf_files:
        try:
            text = _extract_pdf_text(pdf_path)
            source = pdf_path.name
            chunks = _chunk_text(text, source)
            all_chunks.extend(chunks)
        except Exception as exc:
            print(f"  SKIP {pdf_path.name}: {exc}")

    print(f"Total chunks: {len(all_chunks)}")

    # 3. Build TF-IDF index
    print("Building TF-IDF index ...")
    matrix, sources, vectorizer = _build_index(all_chunks)

    # 4. Store via store backend (sqlite / postgres / qdrant — configurable)
    from .store import get_store
    store = get_store()
    print(f"Storing {len(all_chunks)} chunks via {store.__class__.__name__} ...")
    store.insert(all_chunks)

    # 5. Save vectorizer + sparse matrix
    import pickle
    import scipy.sparse
    scipy.sparse.save_npz(str(INDEX_DIR / "tfidf_matrix.npz"), matrix)
    with open(INDEX_DIR / "vectorizer.pkl", "wb") as f:
        pickle.dump(vectorizer, f)
    with open(INDEX_DIR / "chunk_sources.json", "w") as f:
        json.dump([c["source"] for c in all_chunks], f, ensure_ascii=False)
    with open(INDEX_DIR / "chunk_texts.json", "w") as f:
        json.dump([c["text"] for c in all_chunks], f, ensure_ascii=False)

    # 6. Metadata
    meta = {
        "total_pdfs": len(pdf_files),
        "total_chunks": len(all_chunks),
        "total_chars": sum(len(c["text"]) for c in all_chunks),
        "index_features": matrix.shape[1],
    }
    with open(INDEX_DIR / "meta.json", "w") as f:
        json.dump(meta, f)

    print(f"Done: {json.dumps(meta, ensure_ascii=False)}")
    return meta


if __name__ == "__main__":
    ingest()
