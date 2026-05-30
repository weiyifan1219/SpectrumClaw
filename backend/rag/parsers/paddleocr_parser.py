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
        if not self.configured():
            raise RuntimeError(
                "PaddleOCRParser not available. Install: pip install paddlepaddle paddleocr.\n"
                "PaddleOCR is for scanned/image-based PDFs. For standard PDFs use pypdf or MinerU."
            )
        raise NotImplementedError(
            "PaddleOCR parsing logic is not yet implemented. "
            "The parser dependency is installed but the extraction loop needs "
            "PDF page rendering + OCR text extraction, which requires further work. "
            "Use pypdf or MinerU parser instead."
        )
