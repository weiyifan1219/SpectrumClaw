"""Backwards-compatible re-exports from schemas."""

from .schemas.block import SpectrumContentBlock, BlockType
from .schemas.document import SpectrumDocument
from .schemas.graph import SpectrumEntity, SpectrumRelation, ExtractionResult

__all__ = [
    "SpectrumContentBlock", "BlockType",
    "SpectrumDocument",
    "SpectrumEntity", "SpectrumRelation", "ExtractionResult",
]
