"""ContextBuilder — gather surrounding context for each block during processing."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..schemas.document import SpectrumDocument
from ..schemas.block import SpectrumContentBlock


@dataclass
class BlockContext:
    block_id: str = ""
    window_text: str = ""
    section_title: str = ""
    page_title: str = ""
    caption_text: str = ""
    footnote_text: str = ""
    same_page_blocks: list[str] = field(default_factory=list)
    parent_block: dict | None = None
    total_tokens: int = 0

    @property
    def combined(self) -> str:
        parts = []
        if self.section_title:
            parts.append(f"[Section: {self.section_title}]")
        if self.page_title:
            parts.append(f"[Page title: {self.page_title}]")
        if self.caption_text:
            parts.append(f"[Caption: {self.caption_text}]")
        if self.footnote_text:
            parts.append(f"[Footnotes: {self.footnote_text}]")
        if self.window_text:
            parts.append(self.window_text)
        return "\n".join(parts)


class ContextBuilder:
    """Builds context for any block in a document.

    Gathers surrounding text blocks, section headers, captions,
    footnotes, and same-page blocks.
    """

    def __init__(
        self,
        window_size: int = 2,
        max_tokens: int = 2000,
        include_headers: bool = True,
        include_captions: bool = True,
        include_footnotes: bool = True,
    ):
        self.window_size = window_size
        self.max_tokens = max_tokens
        self.include_headers = include_headers
        self.include_captions = include_captions
        self.include_footnotes = include_footnotes

    def build_from_blocks(self, blocks: list[SpectrumContentBlock], block_idx: int) -> BlockContext:
        """Build context from a flat list of blocks (no document wrapper needed)."""
        return self._build(blocks, block_idx)

    def build(self, doc: SpectrumDocument, block_idx: int) -> BlockContext:
        """Build context from a SpectrumDocument."""
        return self._build(doc.blocks, block_idx)

    def _build(self, blocks: list[SpectrumContentBlock], block_idx: int) -> BlockContext:
        if block_idx < 0 or block_idx >= len(blocks):
            return BlockContext()

        center = blocks[block_idx]
        ctx = BlockContext(block_id=center.block_id)

        # ── surrounding text blocks ──
        window_parts: list[str] = []
        for i in range(
            max(0, block_idx - self.window_size),
            min(len(blocks), block_idx + self.window_size + 1),
        ):
            if i == block_idx:
                continue
            b = blocks[i]
            if b.block_type in ("text", "title"):
                snippet = b.content[:300]
                window_parts.append(snippet)
        ctx.window_text = "\n".join(window_parts)

        # ── section title (nearest title block before this one) ──
        if self.include_headers:
            for i in range(block_idx - 1, -1, -1):
                if blocks[i].block_type == "title":
                    ctx.section_title = blocks[i].content[:200]
                    break

        # ── page title ──
        for b in blocks:
            if b.page_idx == center.page_idx and b.block_type == "title":
                ctx.page_title = b.content[:200]
                break

        # ── captions and footnotes ──
        if self.include_captions and center.caption:
            ctx.caption_text = " ".join(center.caption)
        if self.include_footnotes and center.footnote:
            ctx.footnote_text = " ".join(center.footnote)

        # ── same-page blocks ──
        ctx.same_page_blocks = [
            b.block_id for b in blocks
            if b.page_idx == center.page_idx and b.block_id != center.block_id
        ]

        # ── token estimate ──
        ctx.total_tokens = len(ctx.combined.split())

        return ctx
