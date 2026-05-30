"""DoclingParser — IBM Docling-based structured PDF parsing (layout-aware, table/formula detection)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import BaseDocumentParser, ParserConfig

if TYPE_CHECKING:
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
        raise NotImplementedError(
            "DoclingParser is detected but not implemented yet. "
            "Use SPECTRUMCLAW_PARSER=pypdf until the Docling adapter maps "
            "Docling output into SpectrumDocument blocks."
        )
