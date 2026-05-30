"""PaddleOCRParser — OCR-based PDF parsing for scanned documents.

Requires: pip install paddlepaddle paddleocr
"""

from __future__ import annotations

import os
from .base import BaseDocumentParser, ParserConfig
from ..schemas.document import SpectrumDocument


class PaddleOCRParser(BaseDocumentParser):
    """OCR parser for scanned/image-based PDFs. Requires PaddleOCR installation."""

    name = "paddleocr"
    version = "1.0.0"

    def __init__(self):
        self._config = ParserConfig()
        self._lang = "en"

    def configure(self, config: ParserConfig):
        self._config = config
        self._lang = config.metadata.get("lang", "en")

    def configured(self) -> bool:
        try:
            import paddleocr  # noqa
            return True
        except ImportError:
            return False

    def parse(self, file_path: str) -> SpectrumDocument:
        doc_id = SpectrumDocument.make_doc_id(file_path)
        if not self.configured():
            raise RuntimeError("PaddleOCRParser not available. Install with: pip install paddlepaddle paddleocr")
        return SpectrumDocument(
            doc_id=doc_id,
            filename=os.path.basename(file_path),
            source_path=file_path,
            blocks=[],
            metadata={"parser": self.name, "parser_version": self.version, "status": "stub"},
        )
