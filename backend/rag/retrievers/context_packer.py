"""Context packer — deduplicate, merge, limit tokens, preserve sources."""

from __future__ import annotations


class ContextPacker:
    """Pack retrieved results into LLM-ready context with dedup and source tracking."""

    def __init__(self, max_tokens: int = 4000, max_blocks: int = 15):
        self.max_tokens = max_tokens
        self.max_blocks = max_blocks

    def pack(self, results: list[dict]) -> PackedContext:
        deduped = self._deduplicate(results)
        merged = self._merge_same_page(deduped)
        limited = merged[:self.max_blocks]

        ctx_parts: list[str] = []
        citations: list[dict] = []
        seen_sources = set()

        for r in limited:
            meta = r.get("metadata", {})
            source = meta.get("source_path", "unknown")
            page = meta.get("page_idx", "?")
            block_type = meta.get("block_type", "text")
            text = r.get("text", "")
            score = r.get("rerank_score", r.get("score", 0))

            if len(text) > 600:
                text = text[:600] + "..."

            label = f"[{len(citations) + 1}]"
            ctx_parts.append(
                f"{label} {source} (p.{page}, {block_type}, score={score:.3f})\n{text}"
            )

            if source not in seen_sources:
                citations.append({
                    "source": source,
                    "doc_id": meta.get("doc_id", ""),
                    "page": page,
                    "block_id": r.get("block_id", ""),
                    "relevance": score,
                })
                seen_sources.add(source)

        final_context = "\n\n".join(ctx_parts)

        # rough token estimate: 1 token ≈ 4 chars
        if len(final_context) > self.max_tokens * 4:
            final_context = final_context[:self.max_tokens * 4]

        return PackedContext(
            context_text=final_context,
            citations=citations,
            block_count=len(limited),
            total_retrieved=len(results),
        )

    @staticmethod
    def _deduplicate(results: list[dict]) -> list[dict]:
        seen = set()
        out = []
        for r in results:
            bid = r.get("block_id", "")
            if bid in seen:
                continue
            seen.add(bid)
            out.append(r)
        return out

    @staticmethod
    def _merge_same_page(results: list[dict]) -> list[dict]:
        """Merge blocks from the same doc+page into a single entry."""
        pages: dict[tuple, list[dict]] = {}
        for r in results:
            meta = r.get("metadata", {})
            key = (meta.get("source_path", ""), meta.get("page_idx", 0))
            pages.setdefault(key, []).append(r)

        merged = []
        for key, blocks in pages.items():
            if len(blocks) == 1:
                merged.extend(blocks)
            else:
                source, page = key
                texts = [b.get("text", "") for b in blocks]
                best_score = max(b.get("rerank_score", b.get("score", 0)) for b in blocks)
                block_types = {b.get("metadata", {}).get("block_type", "") for b in blocks}
                merged.append({
                    "block_id": blocks[0].get("block_id", ""),
                    "text": "\n---\n".join(texts),
                    "metadata": {
                        "source_path": source,
                        "page_idx": page,
                        "block_type": "+".join(sorted(block_types)),
                    },
                    "rerank_score": best_score,
                })
        return merged


from dataclasses import dataclass, field


@dataclass
class PackedContext:
    context_text: str
    citations: list[dict] = field(default_factory=list)
    block_count: int = 0
    total_retrieved: int = 0
