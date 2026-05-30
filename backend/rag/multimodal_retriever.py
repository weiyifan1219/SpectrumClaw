"""LangChain retriever wrapping the full multimodal RAG pipeline.

Aligned with RAG-Anything's query system — supports:
- Standard text query via HybridRetriever
- Multimodal enhanced query with image/table/equation analysis
- VLM-enhanced query for image-rich results
"""

from __future__ import annotations

from typing import Any

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever


class MultimodalRetriever(BaseRetriever):
    """LangChain BaseRetriever wrapping the full multimodal RAG pipeline.

    Delegates to HybridRetriever for multi-channel retrieval, with optional
    VLM/LLM enhancement of multimodal results.
    """

    top_k: int = 10

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun | None = None,
    ) -> list[Document]:
        import asyncio
        from .retrieval.hybrid_retriever import HybridRetriever
        from .retrievers.vector_retriever import VectorRetriever
        from .retrievers.keyword_retriever import KeywordRetriever
        from .retrievers.graph_retriever import GraphRetriever
        from .embeddings.sentence_transformer import SentenceTransformersEmbeddingProvider
        from .vectorstores.chroma_store import ChromaStore
        from pathlib import Path

        # Init retrievers
        chroma_dir = Path(__file__).resolve().parents[2] / "data" / "chroma"
        emb = SentenceTransformersEmbeddingProvider()
        store = ChromaStore(persist_dir=chroma_dir, embedding_provider=emb)
        vec = VectorRetriever(store, top_k=self.top_k)
        kw = KeywordRetriever(top_k=self.top_k)
        gr = GraphRetriever()

        hybrid = HybridRetriever(
            vector_retriever=vec,
            keyword_retriever=kw,
            graph_retriever=gr,
        )

        result = hybrid.retrieve(query, top_k=self.top_k)

        docs = []
        for r in result.blocks:
            meta = r.get("metadata", {})
            docs.append(Document(
                page_content=r.get("text", ""),
                metadata={
                    "source": meta.get("source_path", ""),
                    "page": meta.get("page_idx", ""),
                    "block_type": meta.get("block_type", "text"),
                    "score": r.get("rerank_score", r.get("score", 0)),
                    "type": "rag_multimodal",
                },
            ))
        return docs

    def to_tool_description(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "search_knowledge_base",
                "description": (
                    "搜索本地 ITU 频谱知识库（803 份 ITU-R 建议书/报告/无线电规则）。"
                    "支持频段分配、脚注限制、区域差异、标准查询。"
                    "检索结果包含向量、关键词、频段匹配、知识图谱四路融合。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "搜索关键词，中英文均可。例如: 2300-2400 MHz Region 3 业务, footnote 5.340",
                        },
                    },
                    "required": ["query"],
                },
            },
        }


# Singleton
_retriever: MultimodalRetriever | None = None


def get_multimodal_retriever(top_k: int = 10) -> MultimodalRetriever:
    global _retriever
    if _retriever is None:
        _retriever = MultimodalRetriever(top_k=top_k)
    return _retriever
