"""TextModalProcessor — clean text, recognize spectrum entities, generate enhanced_content."""

from __future__ import annotations

import re

from ..schemas.block import SpectrumContentBlock
from ..context.builder import BlockContext

FREQ_PATTERN = re.compile(
    r"(\d{1,4}\s*[-–]\s*\d{1,4}\s*(?:MHz|kHz|GHz|Hz))|"
    r"(\d{2,5}\s*(?:MHz|kHz|GHz|Hz))",
    re.IGNORECASE,
)
FOOTNOTE_PATTERN = re.compile(r"(5\.\d{3}[A-Z]?)")
STANDARD_PATTERN = re.compile(
    r"(ITU-R\s+(?:M|F|S|P|BO|BS|BT|RA|RS|SA|SF|SM|SNG|TF)\.?\s*\d+[-\w]*)",
    re.IGNORECASE,
)
REGION_PATTERN = re.compile(r"(Region\s+[1-3])", re.IGNORECASE)


class TextModalProcessor:
    name = "text_modal"

    def process(self, block: SpectrumContentBlock, context: BlockContext | None = None) -> SpectrumContentBlock:
        text = block.raw_content or block.content
        cleaned = self._clean(text)
        block.content = cleaned

        freq_ranges = self._extract_freqs(text)
        footnotes = list(set(FOOTNOTE_PATTERN.findall(text)))
        standards = list(set(STANDARD_PATTERN.findall(text)))
        regions = list(set(REGION_PATTERN.findall(text)))

        heading = self._extract_heading(text)
        if heading:
            block.section_path = [heading]

        parts = [cleaned]
        if freq_ranges:
            parts.append(f"[Frequencies: {', '.join(freq_ranges)}]")
        if footnotes:
            parts.append(f"[Footnotes: {', '.join(footnotes)}]")
        if standards:
            parts.append(f"[Standards: {', '.join(standards)}]")
        if regions:
            parts.append(f"[Regions: {', '.join(regions)}]")

        block.enhanced_content = " ".join(parts)
        block.metadata["freq_ranges"] = freq_ranges
        block.metadata["footnotes"] = footnotes
        block.metadata["standards"] = standards
        block.metadata["regions"] = regions
        block.processing_status = "enhanced"
        return block

    @staticmethod
    def _clean(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _extract_heading(text: str) -> str | None:
        lines = text.split("\n")[:3]
        for line in lines:
            line = line.strip()
            if not line or len(line) > 120:
                continue
            if any(kw in line.lower() for kw in [
                "annex", "appendix", "article", "section", "chapter",
                "introduction", "scope", "reference", "recommend",
                "frequency", "allocation", "characteristic", "protection",
            ]):
                return line
        return None

    @staticmethod
    def _extract_freqs(text: str) -> list[str]:
        ranges = []
        singles = []
        for m in FREQ_PATTERN.findall(text):
            if m[0]:
                ranges.append(m[0])
            if m[1]:
                singles.append(m[1])
        for s in singles:
            if not any(s.replace(" ", "").lower() in r.replace(" ", "").lower()
                        for r in ranges):
                ranges.append(s)
        return list(dict.fromkeys(ranges))
