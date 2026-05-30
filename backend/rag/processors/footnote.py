"""Footnote processor — extract and annotate ITU-R footnote references."""

from __future__ import annotations

import re

from ..models import SpectrumContentBlock


class FootnoteProcessor:
    """Identifies ITU-R footnote numbers and enhances context."""

    FOOTNOTE_REF = re.compile(r"(5\.\d{3}[A-Z]?)")

    def process(self, block: SpectrumContentBlock) -> SpectrumContentBlock:
        text = block.content
        refs = self.FOOTNOTE_REF.findall(text)
        if refs:
            unique_refs = list(dict.fromkeys(refs))
            block.enhanced_content = (
                f"{text}\n[Referenced footnotes: {', '.join(unique_refs)}]"
            )
            block.metadata["footnotes"] = unique_refs
        else:
            block.enhanced_content = text
        return block
