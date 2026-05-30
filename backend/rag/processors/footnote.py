"""FootnoteModalProcessor — extract footnote references with affected bands/regions/services."""

from __future__ import annotations

import re

from ..schemas.block import SpectrumContentBlock
from ..context.builder import BlockContext

FOOTNOTE_REF = re.compile(r"(5\.\d{3}[A-Z]?)")
FREQ_NEAR = re.compile(r"(\d{1,4}\s*[-–]\s*\d{1,4}\s*(?:MHz|kHz|GHz|Hz))", re.IGNORECASE)
REGION_NEAR = re.compile(r"(Region\s+[1-3])", re.IGNORECASE)


class FootnoteModalProcessor:
    name = "footnote_modal"

    def process(self, block: SpectrumContentBlock, context: BlockContext | None = None) -> SpectrumContentBlock:
        text = block.raw_content or block.content
        refs = list(set(FOOTNOTE_REF.findall(text)))

        if not refs:
            block.enhanced_content = text
            block.processing_status = "enhanced"
            return block

        block.footnote = refs
        block.metadata["footnotes"] = refs

        # find affected frequencies near footnotes
        freq_near = list(set(FREQ_NEAR.findall(text)))
        region_near = list(set(REGION_NEAR.findall(text)))

        extra = []
        if freq_near:
            extra.append(f"Affected frequencies: {', '.join(freq_near)}")
            block.metadata["affected_freqs"] = freq_near
        if region_near:
            extra.append(f"Affected regions: {', '.join(region_near)}")

        block.enhanced_content = (
            f"Footnote {', '.join(refs)}: {text}. " + ". ".join(extra)
        )
        block.processing_status = "enhanced"

        # populate entities
        for fn in refs:
            block.entities.append({"name": fn, "type": "Footnote", "block_id": block.block_id})
        for fb in freq_near:
            block.entities.append({"name": fb, "type": "FrequencyBand", "block_id": block.block_id})

        # relations: footnote limits frequencies
        for fn in refs:
            for fb in freq_near:
                block.relations.append({
                    "source": fn, "relation": "limited_by", "target": fb,
                    "evidence_block_id": block.block_id,
                })

        return block
