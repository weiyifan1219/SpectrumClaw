"""MinerU parser stub — reserved for future structured PDF parsing."""

from __future__ import annotations

from .base import BaseDocumentParser
from ..models import SpectrumDocument


class MinerUParser(BaseDocumentParser):
    """Stub: MinerU-based structured document parser (table/formula-aware)."""

    name = "mineru"

    def parse(self, file_path: str) -> SpectrumDocument:
        raise NotImplementedError(
            "MinerUParser is not yet implemented. Install magic-pdf and configure MINERU_ENABLED=true."
        )
