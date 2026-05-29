"""Citation formatting — ITU document numbers, URLs, source annotation."""

from __future__ import annotations

from langchain_core.documents import Document


def format_citations(docs: list[Document], max_sources: int = 5) -> str:
    """Format retrieved documents as a citation block for LLM context."""
    if not docs:
        return ""

    lines = ["\n--- 引用来源 ---\n"]
    for i, doc in enumerate(docs[:max_sources], 1):
        source = doc.metadata.get("source", "unknown")
        score = doc.metadata.get("score", 0)
        lines.append(f"[{i}] 📄 {source} (相关性: {score:.4f})")
    return "\n".join(lines)


def rag_context(docs: list[Document], query: str) -> str:
    """Build RAG context block for injection into LLM messages."""
    if not docs:
        return ""

    ctx = f'知识库检索: "{query}" — 共 {len(docs)} 条结果\n\n'
    for i, doc in enumerate(docs, 1):
        source = doc.metadata.get("source", "")
        score = doc.metadata.get("score", 0)
        text = doc.page_content[:800]
        ctx += f"[{i}] 📄 {source} (相关性: {score:.4f})\n{text}\n\n"

    ctx += "请基于以上知识库内容回答用户问题。如果知识库中没有相关信息，请如实说明，并建议使用 web_search。"
    return ctx
