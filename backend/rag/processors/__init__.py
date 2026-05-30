"""Multi-modal processors — modality-aware block enhancement with context."""

from .text import TextModalProcessor
from .table import TableModalProcessor
from .image import ImageModalProcessor
from .equation import EquationModalProcessor
from .footnote import FootnoteModalProcessor
from .generic import GenericModalProcessor
from ..schemas.block import SpectrumContentBlock
from ..context.builder import BlockContext


def get_processor(block_type: str, **kwargs):
    """Return the appropriate processor for a given block type."""
    mapping = {
        "text": TextModalProcessor,
        "title": TextModalProcessor,
        "table": TableModalProcessor,
        "image": ImageModalProcessor,
        "equation": EquationModalProcessor,
        "footnote": FootnoteModalProcessor,
    }
    cls = mapping.get(block_type, GenericModalProcessor)
    return cls(**kwargs)


def process_block(block: SpectrumContentBlock, context: BlockContext | None = None,
                  **kwargs) -> SpectrumContentBlock:
    """Process a single block with its modality-appropriate processor."""
    proc = get_processor(block.block_type, **kwargs)
    return proc.process(block, context)


def process_document_blocks(blocks: list[SpectrumContentBlock],
                            context_builder=None) -> list[SpectrumContentBlock]:
    """Process all blocks in a document, returning sub-blocks (e.g., table rows)."""
    all_blocks = []
    for i, block in enumerate(blocks):
        ctx = context_builder.build_from_blocks(blocks, i) if context_builder else None
        proc = get_processor(block.block_type)
        enhanced = proc.process(block, ctx)
        all_blocks.append(enhanced)
        # table: extract row sub-blocks
        if block.block_type == "table" and isinstance(proc, TableModalProcessor):
            sub_blocks = proc.create_row_blocks(enhanced)
            all_blocks.extend(sub_blocks)
    return all_blocks


__all__ = [
    "TextModalProcessor", "TableModalProcessor",
    "ImageModalProcessor", "EquationModalProcessor",
    "FootnoteModalProcessor", "GenericModalProcessor",
    "get_processor", "process_block", "process_document_blocks",
]
