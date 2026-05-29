"""LangChain BaseRetriever wrapping the TF-IDF knowledge base search."""

from __future__ import annotations

from typing import Any

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever


class SpectrumRetriever(BaseRetriever):
    """LangChain retriever for the ITU spectrum knowledge base.

    Wraps the existing TF-IDF search backend.
    """

    top_k: int = 5

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun | None = None
    ) -> list[Document]:
        from ..knowledge.retrieve import search, is_ready
        if not is_ready():
            return []

        results = search(query, top_k=self.top_k)
        docs = []
        for r in results:
            docs.append(Document(
                page_content=r["text"][:1200],
                metadata={
                    "source": r["source"],
                    "score": r.get("score", 0),
                    "type": "itu_knowledge_base",
                },
            ))
        return docs

    def to_tool_description(self) -> dict[str, Any]:
        """OpenAI-compatible tool schema for this retriever."""
        return {
            "type": "function",
            "function": {
                "name": "search_knowledge_base",
                "description": (
                    "搜索本地 ITU 频谱知识库（804 份 ITU-R 建议书、报告、无线电规则）。"
                    "用于查询频谱法规、频段分配、干扰标准、技术参数等专业问题。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "搜索关键词，用中文或英文。例如: VHF 频段分配, 干扰保护标准",
                        },
                    },
                    "required": ["query"],
                },
            },
        }


# singleton
_retriever: SpectrumRetriever | None = None


def get_retriever(top_k: int = 5) -> SpectrumRetriever:
    global _retriever
    if _retriever is None:
        _retriever = SpectrumRetriever(top_k=top_k)
    return _retriever
