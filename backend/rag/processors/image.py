"""ImageModalProcessor — VLM-powered image understanding with fallback."""

from __future__ import annotations

from ..schemas.block import SpectrumContentBlock
from ..context.builder import BlockContext


class ImageModalProcessor:
    name = "image_modal"

    def __init__(self, vlm_client=None):
        self.vlm = vlm_client  # VLMClient instance, or None for placeholder mode

    def process(self, block: SpectrumContentBlock, context: BlockContext | None = None) -> SpectrumContentBlock:
        caption = " ".join(block.caption) if block.caption else "[Uncaptioned image]"
        ctx_text = context.window_text if context else ""

        image_path = block.asset_path
        if image_path and self.vlm and self.vlm.configured:
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # Create task — will be awaited later in the pipeline
                    block.modality_summary = f"[VLM pending] Caption: {caption}"
                else:
                    summary = asyncio.run(self.vlm.describe_image(image_path))
                    block.modality_summary = summary
            except RuntimeError:
                summary = asyncio.run(self.vlm.describe_image(image_path))
                block.modality_summary = summary
        else:
            block.modality_summary = (
                f"[Image] Caption: {caption}. "
                f"Page {block.page_idx}, {block.source_path}."
            )

        block.enhanced_content = block.modality_summary
        block.metadata["image_path"] = image_path or ""
        block.metadata["has_image"] = True
        block.processing_status = "enhanced"
        return block

    async def process_async(self, block: SpectrumContentBlock, context: BlockContext | None = None) -> SpectrumContentBlock:
        """Async version — call from async context with VLM available."""
        caption = " ".join(block.caption) if block.caption else "[Uncaptioned]"
        ctx_text = context.window_text if context else ""

        if block.asset_path and self.vlm and self.vlm.configured:
            prompt = (
                f"Analyze this figure from a spectrum management document.\n"
                f"Caption: {caption}\n"
                f"Surrounding text: {ctx_text[:500]}\n"
                f"Describe the image content, focusing on frequency bands, services, "
                f"interference scenarios, or system architectures shown."
            )
            block.modality_summary = await self.vlm.describe_image(block.asset_path, prompt)
        else:
            block.modality_summary = f"[Image] Caption: {caption}. Page {block.page_idx}."

        block.enhanced_content = block.modality_summary
        block.metadata["image_path"] = block.asset_path or ""
        block.metadata["has_image"] = True
        block.processing_status = "enhanced"
        return block
