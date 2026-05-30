"""Context window — gather surrounding blocks for context-aware processing."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..models import SpectrumContentBlock


@dataclass
class ContextWindow:
    """Sliding window over document blocks for context-aware processing."""

    window_size: int = 2
    max_tokens: int = 2000
    include_headers: bool = True
    include_captions: bool = True

    def gather(self, blocks: list[SpectrumContentBlock], center_idx: int) -> ContextResult:
        start = max(0, center_idx - self.window_size)
        end = min(len(blocks), center_idx + self.window_size + 1)

        prev_blocks = blocks[start:center_idx]
        next_blocks = blocks[center_idx + 1:end]
        center = blocks[center_idx]

        context_parts: list[str] = []
        if self.include_headers:
            headers = [b.content for b in prev_blocks if b.block_type == "title"]
            if headers:
                context_parts.append("[Section: " + " > ".join(headers[-2:]) + "]")

        for b in prev_blocks[-self.window_size:]:
            snippet = b.content[:200]
            context_parts.append(snippet)

        if self.include_captions and center.caption:
            context_parts.append(f"[Caption: {center.caption}]")

        for b in next_blocks[:self.window_size]:
            snippet = b.content[:200]
            context_parts.append(snippet)

        return ContextResult(
            context_text="\n".join(context_parts),
            prev_block_ids=[b.block_id for b in prev_blocks],
            next_block_ids=[b.block_id for b in next_blocks],
        )


@dataclass
class ContextResult:
    context_text: str
    prev_block_ids: list[str] = field(default_factory=list)
    next_block_ids: list[str] = field(default_factory=list)
