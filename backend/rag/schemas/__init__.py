"""Schema v2 — multimodal content blocks, documents, entities, and relations."""

from .block import SpectrumContentBlock, BlockType
from .document import SpectrumDocument
from .graph import SpectrumEntity, SpectrumRelation

__all__ = [
    "SpectrumContentBlock", "BlockType",
    "SpectrumDocument",
    "SpectrumEntity", "SpectrumRelation",
]
