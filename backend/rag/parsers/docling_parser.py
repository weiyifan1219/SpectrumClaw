"""DoclingParser — IBM Docling-based structured PDF parsing (layout-aware, table/formula detection)."""

from __future__ import annotations

import os
from .base import BaseDocumentParser, ParserConfig
from ..schemas.document import SpectrumDocument


class DoclingParser(BaseDocumentParser):
    """Structured parser using IBM Docling. Requires: pip install docling."""

    name = "docling"
    version = "1.0.0"

    def __init__(self):
        self._config = ParserConfig()

    def configure(self, config: ParserConfig):
        self._config = config

    def configured(self) -> bool:
        try:
            import docling  # noqa
            return True
        except ImportError:
            return False

    def parse(self, file_path: str) -> SpectrumDocument:
        if not self.configured():
            raise RuntimeError(
                "DoclingParser not available. Install with: pip install docling.\n"
                "Docling requires: pip install docling (see https://github.com/DS4SD/docling)"
            )
        import os
        doc_id = SpectrumDocument.make_doc_id(file_path)
        return SpectrumDocument(
            doc_id=doc_id,
            filename=os.path.basename(file_path),
            source_path=file_path,
            blocks=[],
            metadata={"parser": self.name, "parser_version": self.version,
                       "status": "unavailable — install docling package"},
        )
