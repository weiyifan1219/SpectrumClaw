"""ImageModalProcessor — preserve images with captions, optional VLM description."""

from __future__ import annotations

from ..schemas.block import SpectrumContentBlock
from ..context.builder import BlockContext


class ImageModalProcessor:
    name = "image_modal"

    def __init__(self, vlm_enabled: bool = False, vlm_model: str = ""):
        self.vlm_enabled = vlm_enabled
        self.vlm_model = vlm_model

    def process(self, block: SpectrumContentBlock, context: BlockContext | None = None) -> SpectrumContentBlock:
        caption = " ".join(block.caption) if block.caption else "[Uncaptioned image]"
        ctx_text = context.window_text if context else ""

        if self.vlm_enabled:
            summary = self._call_vlm(block, caption, ctx_text)
        else:
            summary = (
                f"[Image] Caption: {caption}. "
                f"Source: {block.source_path}, page {block.page_idx}."
            )

        block.modality_summary = summary
        block.enhanced_content = summary
        block.metadata["has_image"] = True
        block.processing_status = "enhanced"
        return block

    def _call_vlm(self, block: SpectrumContentBlock, caption: str, context: str) -> str:
        # Placeholder — VLM integration not active per current phase
        # When enabled, this will base64-encode block.asset_path and call the VLM API
        return f"[Image placeholder — VLM not configured] Caption: {caption}"
