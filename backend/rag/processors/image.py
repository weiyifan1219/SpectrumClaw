"""Image processor — placeholder, preserves image path and caption."""

from __future__ import annotations

from ..models import SpectrumContentBlock


class ImageProcessor:
    """Placeholder image processor. Preserves image path and caption.
    VLM-based description generation is reserved for future phases.
    """

    def process(self, block: SpectrumContentBlock) -> SpectrumContentBlock:
        caption = block.caption or "[Image]"
        block.enhanced_content = (
            f"[Image block] Caption: {caption}. "
            f"Source: {block.source_path}, page {block.page_idx}."
        )
        block.metadata["has_image"] = True
        return block
