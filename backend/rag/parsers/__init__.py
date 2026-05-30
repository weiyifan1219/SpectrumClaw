"""Plugable parser registry — pypdf + MinerU + Docling + PaddleOCR."""

from .base import BaseDocumentParser, ParserConfig, ParserFactory
from .pypdf_parser import PyPDFParser
from .mineru_parser import MinerUParser
from .docling_parser import DoclingParser
from .paddleocr_parser import PaddleOCRParser

# Register all parsers
for cls in [PyPDFParser, MinerUParser, DoclingParser, PaddleOCRParser]:
    ParserFactory.register(cls.name, cls)


def create_parser(primary: str = "pypdf", fallback: str = "pypdf",
                  config: ParserConfig | None = None) -> BaseDocumentParser:
    """Create a parser with fallback. Default: pypdf."""
    return ParserFactory.create_with_fallback(primary, fallback, config)


def get_parser(name: str = "pypdf") -> BaseDocumentParser:
    """Get a parser by name. Throws if unavailable."""
    p = ParserFactory.create(name)
    if p is None:
        raise RuntimeError(f"Parser '{name}' not available. "
                           f"Available: {ParserFactory.list_available()}")
    return p


__all__ = [
    "BaseDocumentParser", "ParserConfig", "ParserFactory",
    "PyPDFParser", "MinerUParser", "DoclingParser", "PaddleOCRParser",
    "create_parser", "get_parser",
]
