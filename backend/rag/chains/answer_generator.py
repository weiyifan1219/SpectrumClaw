"""Answer generator — LLM-powered spectrum answer with mandatory citations."""

from __future__ import annotations

from .prompts import SPECTRUM_RAG_SYSTEM_PROMPT, SPECTRUM_RAG_USER_TEMPLATE


class AnswerGenerator:
    """Generate spectrum-domain answers with citations from retrieved context.

    Uses the configured LLM provider for generation.
    """

    async def generate(
        self,
        question: str,
        context: str,
        citations: list[dict],
    ) -> tuple[str, list[dict]]:
        """Generate answer and return (answer_text, enriched_citations)."""
        if not context:
            return (
                "根据当前检索结果，未能找到与您问题相关的频谱文档。"
                "建议：\n1. 尝试使用不同的关键词重新提问\n2. 确认知识库中已索引相关ITU-R文档",
                [],
            )

        system_prompt = SPECTRUM_RAG_SYSTEM_PROMPT
        user_prompt = SPECTRUM_RAG_USER_TEMPLATE.format(
            context=context,
            question=question,
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            from ...llm.client import chat
            from ...config import get_settings

            settings = get_settings()
            provider = settings.provider_profile()
            reply, _meta = await chat(
                messages,
                provider_override=provider.provider,
                model_override=provider.model,
            )
            return reply, citations
        except Exception as exc:
            return (
                f"回答生成失败 (Answer generation failed): {exc}\n\n"
                f"检索到 {len(citations)} 条相关文档，但LLM调用出错。请检查API配置。",
                citations,
            )
