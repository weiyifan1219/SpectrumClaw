"""Docling parser stub — reserved for future structured PDF parsing."""

from __future__ import annotations

from .base import BaseDocumentParser
from ..models import SpectrumDocument


class DoclingParser(BaseDocumentParser):
    """Stub: Docling-based structured document parser (multi-modal, layout-aware)."""

    name = "docling"

    def parse(self, file_path: str) -> SpectrumDocument:
        raise NotImplementedError(
            "DoclingParser is not yet implemented. Install docling and configure DOCLING_ENABLED=true."
        )
