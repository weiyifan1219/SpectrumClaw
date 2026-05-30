"""EquationModalProcessor — LaTeX detection, variable extraction, formula explanation."""

from __future__ import annotations

import re

from ..schemas.block import SpectrumContentBlock
from ..context.builder import BlockContext

LATEX_HINTS = re.compile(r"[\\{}$_^{}]|\\frac|\\sum|\\int|\\alpha|\\beta|\\gamma|\\lambda")


class EquationModalProcessor:
    name = "equation_modal"

    def process(self, block: SpectrumContentBlock, context: BlockContext | None = None) -> SpectrumContentBlock:
        text = block.raw_content or block.content
        is_latex = bool(LATEX_HINTS.search(text))

        if is_latex:
            block.latex = text
            # Simple variable extraction
            vars_found = re.findall(r"\\([a-zA-Z]+)", text)
            var_desc = f"Variables: {', '.join(set(vars_found))}" if vars_found else ""
            block.enhanced_content = f"[Formula (LaTeX)]: {text}. {var_desc}"
            block.modality_summary = f"Mathematical formula with variables: {', '.join(set(vars_found))}" if vars_found else "Mathematical formula"
            block.metadata["variables"] = list(set(vars_found))
        else:
            block.enhanced_content = f"[Formula]: {text}"
            block.modality_summary = "Inline formula"

        block.metadata["is_latex"] = is_latex
        block.processing_status = "enhanced"
        return block
