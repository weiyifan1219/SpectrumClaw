"""GenericModalProcessor — fallback for unknown block types, preserves content."""

from __future__ import annotations

from ..schemas.block import SpectrumContentBlock
from ..context.builder import BlockContext


class GenericModalProcessor:
    name = "generic_modal"

    def process(self, block: SpectrumContentBlock, context: BlockContext | None = None) -> SpectrumContentBlock:
        text = block.raw_content or block.content
        block.enhanced_content = f"[{block.block_type}] {text[:600]}"
        block.modality_summary = f"Generic {block.block_type} block"
        block.processing_status = "enhanced"
        return block
