"""EquationModalProcessor — LaTeX detection, variable extraction, formula explanation."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

from ..schemas.block import SpectrumContentBlock
from ..context.builder import BlockContext

LATEX_HINTS = re.compile(r"[\\{}$_^{}]|\\frac|\\sum|\\int|\\alpha|\\beta|\\gamma|\\lambda")


class EquationModalProcessor:
    name = "equation_modal"

    def __init__(self, vlm_client=None):
        self.vlm = vlm_client

    @staticmethod
    def _has_asset(path: str | None) -> bool:
        return bool(path) and Path(path).exists()

    def process(self, block: SpectrumContentBlock, context: BlockContext | None = None) -> SpectrumContentBlock:
        text = block.raw_content or block.content
        is_latex = bool(LATEX_HINTS.search(text))
        if is_latex:
            block.latex = text

        if self._has_asset(block.asset_path) and self.vlm and self.vlm.configured:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    fallback = self._fallback_summary(text, is_latex)
                    block.modality_summary = str(fallback["summary"])
                    block.enhanced_content = str(fallback["content"])
                    if fallback["variables"]:
                        block.metadata["variables"] = fallback["variables"]
                else:
                    summary = asyncio.run(
                        self.vlm.describe_equation(
                            block.asset_path,
                            equation_text=text,
                            equation_format="latex" if is_latex else "inline",
                            context=context.window_text[:500] if context else "",
                            entity_name=block.caption[0] if block.caption else block.block_id,
                        )
                    )
                    block.modality_summary = summary
                    block.enhanced_content = f"[Formula VLM]: {summary}"
            except RuntimeError:
                summary = asyncio.run(
                    self.vlm.describe_equation(
                        block.asset_path,
                        equation_text=text,
                        equation_format="latex" if is_latex else "inline",
                        context=context.window_text[:500] if context else "",
                        entity_name=block.caption[0] if block.caption else block.block_id,
                    )
                )
                block.modality_summary = summary
                block.enhanced_content = f"[Formula VLM]: {summary}"
        else:
            fallback = self._fallback_summary(text, is_latex)
            block.modality_summary = fallback["summary"]
            block.enhanced_content = fallback["content"]
            if fallback["variables"]:
                block.metadata["variables"] = fallback["variables"]

        block.metadata["is_latex"] = is_latex
        block.processing_status = "enhanced"
        return block

    async def process_async(self, block: SpectrumContentBlock, context: BlockContext | None = None) -> SpectrumContentBlock:
        text = block.raw_content or block.content
        is_latex = bool(LATEX_HINTS.search(text))
        if is_latex:
            block.latex = text
        if self._has_asset(block.asset_path) and self.vlm and self.vlm.configured:
            summary = await self.vlm.describe_equation(
                block.asset_path,
                equation_text=text,
                equation_format="latex" if is_latex else "inline",
                context=context.window_text[:500] if context else "",
                entity_name=block.caption[0] if block.caption else block.block_id,
            )
            block.modality_summary = summary
            block.enhanced_content = f"[Formula VLM]: {summary}"
            block.metadata["is_latex"] = is_latex
            block.processing_status = "enhanced"
            return block
        return self.process(block, context)

    @staticmethod
    def _fallback_summary(text: str, is_latex: bool) -> dict[str, object]:
        vars_found = sorted(set(re.findall(r"\\([a-zA-Z]+)", text))) if is_latex else []
        if is_latex:
            var_desc = f"Variables: {', '.join(vars_found)}" if vars_found else ""
            return {
                "summary": f"Mathematical formula with variables: {', '.join(vars_found)}" if vars_found else "Mathematical formula",
                "content": f"[Formula (LaTeX)]: {text}. {var_desc}".strip(),
                "variables": vars_found,
            }
        return {
            "summary": "Inline formula",
            "content": f"[Formula]: {text}",
            "variables": [],
        }
