"""PyPDF-based PDF parser — extracts text per page into structured blocks."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from pypdf import PdfReader

from .base import BaseDocumentParser
from ..models import SpectrumDocument, SpectrumContentBlock


class PyPDFParser(BaseDocumentParser):
    """Extract text from PDFs via pypdf, producing page-level text blocks.

    Upgraded from the original _extract_pdf_text() — now page-aware and structured.
    """

    name = "pypdf"

    def __init__(self, min_chars: int = 50):
        self.min_chars = min_chars

    def parse(self, file_path: str) -> SpectrumDocument:
        path = Path(file_path)
        filename = path.name
        doc_id = self._make_doc_id(file_path)
        reader = PdfReader(str(path))

        blocks: list[SpectrumContentBlock] = []
        for page_idx, page in enumerate(reader.pages):
            text = page.extract_text()
            if not text or len(text.strip()) < self.min_chars:
                continue
            cleaned = self._clean_page(text)
            if len(cleaned) < self.min_chars:
                continue

            block_type = self._classify_block(cleaned, page_idx)
            block = SpectrumContentBlock.create(
                doc_id=doc_id,
                source_path=str(path),
                page_idx=page_idx + 1,  # 1-based
                block_type=block_type,
                content=cleaned,
                metadata={"parser": "pypdf", "page_label": str(page_idx + 1)},
            )
            blocks.append(block)

        return SpectrumDocument(
            doc_id=doc_id,
            filename=filename,
            source_path=str(path),
            blocks=blocks,
            metadata={"parser": "pypdf", "total_pages": len(reader.pages)},
        )

    # ── helpers ──

    @staticmethod
    def _make_doc_id(file_path: str) -> str:
        return hashlib.md5(file_path.encode()).hexdigest()[:12]

    @staticmethod
    def _clean_page(text: str) -> str:
        lines = text.split("\n")
        kept = []
        for line in lines:
            s = line.strip()
            if not s:
                kept.append("")
                continue
            if re.match(r"^\d+\s*$", s):
                continue
            if re.match(r"^(Rec\.\s*ITU-R|Electronic Publication|Geneva,\s*\d{4})", s, re.IGNORECASE):
                continue
            kept.append(s)
        return "\n".join(kept).strip()

    @staticmethod
    def _classify_block(text: str, page_idx: int) -> str:
        if page_idx == 0 and len(text) < 500:
            return "title"
        return "text"
