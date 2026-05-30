"""Equation processor — preserve LaTeX and generate text description."""

from __future__ import annotations

import re

from ..models import SpectrumContentBlock


class EquationProcessor:
    """Preserves formula content and attempts LaTeX conversion."""

    LATEX_HINTS = re.compile(r"[\\{}$_^{}]|\\frac|\\sum|\\int|\\alpha|\\beta|\\lambda")

    def process(self, block: SpectrumContentBlock) -> SpectrumContentBlock:
        text = block.content
        is_latex = bool(self.LATEX_HINTS.search(text))

        if is_latex:
            block.enhanced_content = f"[Formula (LaTeX)]: {text}"
        else:
            block.enhanced_content = f"[Formula]: {text}"

        block.metadata["is_latex"] = is_latex
        return block
