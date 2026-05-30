"""Query-time multimodal content analysis — table/equation/image enhancement.

Aligned with RAG-Anything's query multimodal analysis pattern:
when retrieved results contain multimodal content, use VLM/LLM to analyze
the specific content in context of the user's question.
"""

from __future__ import annotations

import os
from typing import Any


async def analyze_table_for_query(
    table_data: str,
    table_caption: str = "",
    llm_chat_func=None,
) -> str | None:
    """Analyze a retrieved table in context of a query. Uses LLM or VLM."""
    from ..prompts import PROMPTS
    prompt = PROMPTS["query_table_analysis"].format(
        table_data=table_data[:3000],
        table_caption=table_caption or "none",
    )
    if llm_chat_func:
        try:
            msgs = [
                {"role": "system", "content": PROMPTS["TABLE_ANALYSIS_SYSTEM"]},
                {"role": "user", "content": prompt},
            ]
            return await llm_chat_func(msgs)
        except Exception:
            return None
    return None


async def analyze_equation_for_query(
    latex: str,
    equation_caption: str = "",
    llm_chat_func=None,
) -> str | None:
    """Analyze a retrieved equation for query context."""
    from ..prompts import PROMPTS
    prompt = PROMPTS["query_equation_analysis"].format(
        latex=latex,
        equation_caption=equation_caption or "none",
    )
    if llm_chat_func:
        try:
            msgs = [
                {"role": "system", "content": PROMPTS["EQUATION_ANALYSIS_SYSTEM"]},
                {"role": "user", "content": prompt},
            ]
            return await llm_chat_func(msgs)
        except Exception:
            return None
    return None


async def enhance_retrieved_multimodal(
    retrieved_blocks: list[dict],
    question: str = "",
    llm_chat_func=None,
) -> list[str]:
    """Enhance retrieved multimodal blocks with LLM/VLM analysis.

    Returns list of analysis text snippets to append to final context.
    """
    analyses = []
    vlm = None
    if os.getenv("QWEN_VL_API_KEY"):
        from .vlm_client import QwenVLClient
        vlm = QwenVLClient()

    for block in retrieved_blocks[:10]:
        meta = block.get("metadata", {})
        bt = meta.get("block_type", "text")
        text = block.get("text", "")

        if bt in ("table", "table_row") and llm_chat_func:
            caption = meta.get("caption", "")
            result = await analyze_table_for_query(text, caption, llm_chat_func)
            if result:
                analyses.append(f"[Table analysis] {result}")

        elif bt == "equation" and llm_chat_func:
            latex = meta.get("latex", text)
            cap = meta.get("caption", "")
            result = await analyze_equation_for_query(latex, cap, llm_chat_func)
            if result:
                analyses.append(f"[Equation analysis] {result}")

        elif bt in ("image", "chart") and vlm and vlm.configured:
            img_path = meta.get("image_path", "")
            if img_path and os.path.exists(img_path):
                try:
                    from ..prompts import PROMPTS
                    desc = await vlm.describe_image(
                        img_path,
                        prompt=PROMPTS["query_image_description"],
                    )
                    analyses.append(f"[Image analysis: {img_path}] {desc}")
                except Exception:
                    pass

    return analyses
