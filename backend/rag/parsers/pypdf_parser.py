"""PyPDFParser — page-level extraction producing SpectrumContentBlocks."""

from __future__ import annotations

import re
from pathlib import Path

from pypdf import PdfReader

from .base import BaseDocumentParser, ParserConfig
from ..schemas.document import SpectrumDocument
from ..schemas.block import SpectrumContentBlock


class PyPDFParser(BaseDocumentParser):
    """Extract text from PDFs page by page. Fallback parser for all PDF types."""

    name = "pypdf"
    version = "2.0.0"

    def __init__(self, min_chars: int = 50):
        self.min_chars = min_chars
        self._config = ParserConfig()

    def configure(self, config: ParserConfig):
        self._config = config

    def parse(self, file_path: str) -> SpectrumDocument:
        path = Path(file_path)
        filename = path.name
        doc_id = SpectrumDocument.make_doc_id(file_path)

        reader = PdfReader(str(path))
        blocks = []

        for page_idx, page in enumerate(reader.pages):
            text = page.extract_text()
            if not text or len(text.strip()) < self.min_chars:
                continue
            cleaned = self._clean_page(text)
            if len(cleaned) < self.min_chars:
                continue
            btype = "title" if (page_idx == 0 and len(cleaned) < 500) else "text"
            block = SpectrumContentBlock.create(
                doc_id=doc_id,
                source_path=str(path),
                page_idx=page_idx + 1,
                block_type=btype,
                raw_content=cleaned,
                content=cleaned,
                parser_name="pypdf",
                parser_version=self.version,
                metadata={"parser": "pypdf", "page_label": str(page_idx + 1)},
            )
            blocks.append(block)

        return SpectrumDocument(
            doc_id=doc_id,
            filename=filename,
            source_path=str(path),
            blocks=blocks,
            metadata={"parser": "pypdf", "parser_version": self.version,
                       "total_pages": len(reader.pages)},
        )

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
            if re.match(r"^(Rec\.\s*ITU-R|Electronic Publication|Geneva,\s*\d{4})",
                        s, re.IGNORECASE):
                continue
            kept.append(s)
        return "\n".join(kept).strip()
