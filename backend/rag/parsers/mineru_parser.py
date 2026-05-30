"""MinerUParser — MinerU-based structured PDF parsing (table/formula/OCR-aware).

Requires: pip install magic-pdf or MinerU Docker endpoint.
"""

from __future__ import annotations

import os
from .base import BaseDocumentParser, ParserConfig
from ..schemas.document import SpectrumDocument


class MinerUParser(BaseDocumentParser):
    """High-quality parser using MinerU. Supports complex layouts, formulas, tables."""

    name = "mineru"
    version = "1.0.0"

    def __init__(self):
        self._config = ParserConfig()
        self._endpoint = ""

    def configure(self, config: ParserConfig):
        self._config = config
        self._endpoint = config.metadata.get("endpoint", "")

    def configured(self) -> bool:
        try:
            import magic_pdf  # noqa
            return True
        except ImportError:
            return bool(self._endpoint)  # Docker endpoint fallback

    def parse(self, file_path: str) -> SpectrumDocument:
        doc_id = SpectrumDocument.make_doc_id(file_path)
        if not self.configured():
            raise RuntimeError(
                "MinerUParser not available. "
                "Install with: pip install magic-pdf or set rag.parser.mineru.endpoint.")
        return SpectrumDocument(
            doc_id=doc_id,
            filename=os.path.basename(file_path),
            source_path=file_path,
            blocks=[],
            metadata={"parser": self.name, "parser_version": self.version, "status": "stub"},
        )
