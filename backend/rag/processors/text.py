"""Text processor — clean, preserve headers, recognize spectrum patterns."""

from __future__ import annotations

import re

from ..models import SpectrumContentBlock


# Patterns for spectrum-domain entities
FREQ_PATTERN = re.compile(
    r"(\d{1,4}\s*[-–]\s*\d{1,4}\s*(MHz|kHz|GHz|Hz))|"
    r"(\d{2,5}\s*(MHz|kHz|GHz|Hz))",
    re.IGNORECASE,
)
FOOTNOTE_PATTERN = re.compile(r"(5\.\d{3}[A-Z]?)")
STANDARD_PATTERN = re.compile(
    r"(ITU-R\s+(M|F|S|P|BO|BS|BT|RA|RS|SA|SF|SM|SNG|TF)\.\s*\d+[-\w]*)",
    re.IGNORECASE,
)
REGION_PATTERN = re.compile(r"(Region\s+[1-3])", re.IGNORECASE)
# ITU-R defines 3 Regions:
#   Region 1 — Europe, Africa, Middle East, former USSR
#   Region 2 — The Americas & Greenland
#   Region 3 — Asia-Pacific, Australia, Oceania
SECTION_PATTERN = re.compile(
    r"^(?:(\d+(?:\.\d+)*)\s+)?([A-Z][A-Za-z\s\-/]{3,80})$",
    re.MULTILINE,
)


class TextProcessor:
    """Cleans text and annotates spectrum-domain entities."""

    def process(self, block: SpectrumContentBlock) -> SpectrumContentBlock:
        text = self._clean(block.content)
        freq_ranges = FREQ_PATTERN.findall(text)
        footnotes = FOOTNOTE_PATTERN.findall(text)
        standards = STANDARD_PATTERN.findall(text)
        regions = REGION_PATTERN.findall(text)

        # Extract heading
        section_path = list(block.section_path)
        heading = self._extract_heading(text)
        if heading:
            section_path.append(heading)

        # Build enhanced content
        parts = [text]
        if freq_ranges:
            parts.append(f"[Frequency ranges: {', '.join(flatten_freqs(freq_ranges))}]")
        if footnotes:
            parts.append(f"[Footnotes: {', '.join(footnotes)}]")
        if standards:
            parts.append(f"[Standards: {', '.join(flatten_standards(standards))}]")
        if regions:
            parts.append(f"[Regions: {', '.join(regions)}]")

        block.enhanced_content = " ".join(parts)
        block.section_path = section_path
        block.metadata["freq_ranges"] = flatten_freqs(freq_ranges)
        block.metadata["footnotes"] = footnotes
        block.metadata["standards"] = flatten_standards(standards)
        block.metadata["regions"] = regions
        return block

    @staticmethod
    def _clean(text: str) -> str:
        # Collapse whitespace
        text = re.sub(r"\s+", " ", text)
        # Remove page numbers standing alone
        text = re.sub(r"\b\d{1,4}\b\s*$", "", text.strip())
        return text.strip()

    @staticmethod
    def _extract_heading(text: str) -> str | None:
        lines = text.split("\n")[:3]
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if len(line) < 100 and any(
                kw in line.lower()
                for kw in ["annex", "appendix", "article", "section", "chapter",
                           "introduction", "scope", "reference", "definition",
                           "recommend", "table of", "contents", "frequency",
                           "allocation", "characteristic", "protection"]
            ):
                return line
        return None


def flatten_freqs(freq_matches: list[tuple]) -> list[str]:
    """Flatten regex frequency matches to unique strings, deduplicating sub-matches."""
    range_freqs = []
    single_freqs = []
    for m in freq_matches:
        range_val = m[0]  # e.g. "2300-2400 MHz"
        single_val = m[2]  # e.g. "2400 MHz"
        if range_val:
            range_freqs.append(range_val)
        if single_val:
            single_freqs.append(single_val)

    # Remove single freqs that appear within a range
    result = list(range_freqs)
    for sf in single_freqs:
        sf_clean = sf.replace(" ", "").lower()
        if not any(sf_clean in rf.replace(" ", "").lower() for rf in range_freqs):
            result.append(sf)

    # Deduplicate preserving order
    seen = set()
    unique = []
    for r in result:
        if r not in seen:
            seen.add(r)
            unique.append(r)
    return unique


def flatten_standards(std_matches: list[tuple]) -> list[str]:
    results = []
    seen = set()
    for m in std_matches:
        s = m[0]
        if s and s not in seen:
            seen.add(s)
            results.append(s)
    return results
