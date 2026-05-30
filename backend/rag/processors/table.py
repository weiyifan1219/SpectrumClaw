"""TableModalProcessor — structured table → NL with optional LLM enhancement."""

from __future__ import annotations

import re

from ..schemas.block import SpectrumContentBlock, BlockType
from ..context.builder import BlockContext


class TableModalProcessor:
    """Detect tables, convert to markdown + natural language, create row sub-blocks.

    Two modes:
    - Rule-based (default): pattern matching for pipe/tab/space-aligned tables
    - LLM-enhanced: sends table markdown to LLM for richer semantic description
    """

    name = "table_modal"

    def __init__(self, llm_chat_func=None):
        """llm_chat_func: async fn(messages) -> str for LLM-enhanced mode."""
        self.llm_chat = llm_chat_func

    def process(self, block: SpectrumContentBlock, context: BlockContext | None = None) -> SpectrumContentBlock:
        text = block.raw_content or block.content
        rows = self._detect_table(text)

        if not rows or len(rows) < 2:
            block.enhanced_content = text
            block.processing_status = "enhanced"
            return block

        headers = rows[0]
        data = rows[1:]

        # build markdown table
        md_lines = ["| " + " | ".join(headers) + " |",
                     "|" + "|".join(["---"] * len(headers)) + "|"]
        for row in data[:50]:
            padded = row + [""] * (len(headers) - len(row))
            md_lines.append("| " + " | ".join(padded) + " |")
        block.table_markdown = "\n".join(md_lines)

        # rule-based NL (LLM enhancement happens in async path)
        caption = " ".join(block.caption) if block.caption else "Table"
        nl_parts = [f"{caption}. Columns: {', '.join(headers)}."]
        for i, row in enumerate(data[:40]):
            row_desc = [f"{h}: {v}" for h, v in zip(headers, row)
                        if v and v not in ("-", "—", "N/A", "", "/")]
            if row_desc:
                nl_parts.append(f"Row {i + 1}: {'; '.join(row_desc)}.")

        # spectrum-specific enrichment
        freq_cols = self._find_freq_columns(headers, data)
        region_cols = self._find_region_columns(headers, data)
        svc_cols = self._find_service_columns(headers, data)
        if freq_cols:
            nl_parts.append(f"[Frequency columns: {', '.join(freq_cols)}]")
        if region_cols:
            nl_parts.append(f"[Region columns: {', '.join(region_cols)}]")

        block.enhanced_content = " ".join(nl_parts)
        block.table_rows = [
            {h: r[i] if i < len(r) else "" for i, h in enumerate(headers)}
            for r in data
        ]
        block.processing_status = "enhanced"
        block.metadata["table_headers"] = headers
        block.metadata["row_count"] = len(data)
        block.metadata["freq_columns"] = freq_cols
        block.metadata["region_columns"] = region_cols
        return block

    async def process_async(self, block: SpectrumContentBlock, context: BlockContext | None = None) -> SpectrumContentBlock:
        """Async table processing with optional LLM enhancement."""
        # Run rule-based first
        self.process(block, context)

        if self.llm_chat and block.table_markdown:
            try:
                caption = " ".join(block.caption) if block.caption else ""
                prompt = (
                    "You are analyzing a spectrum allocation table from an ITU-R document. "
                    "Convert the following markdown table into a detailed natural language "
                    "description. For each row, state: 'Frequency band X is allocated to "
                    "service Y in Region Z, with constraint W (if any).' "
                    "Preserve all numerical values and units exactly. "
                    "Focus on frequency ranges, radio services, ITU regions, "
                    "footnote references, and allocation status (primary/secondary). "
                    f"Table caption: {caption}\n\n{block.table_markdown}"
                )
                msgs = [{"role": "user", "content": prompt}]
                result = await self.llm_chat(msgs)
                if result:
                    block.enhanced_content = f"{block.enhanced_content}\n[LLM]: {result}"
            except Exception:
                pass  # fall back to rule-based

        return block

    def create_row_blocks(self, parent: SpectrumContentBlock) -> list[SpectrumContentBlock]:
        """Create standalone retrievable blocks for each table row."""
        if not parent.table_rows:
            return []
        sub_blocks = []
        for i, row in enumerate(parent.table_rows):
            nl = "; ".join(f"{k}: {v}" for k, v in row.items() if v)
            sub = SpectrumContentBlock.create(
                doc_id=parent.doc_id,
                source_path=parent.source_path,
                page_idx=parent.page_idx,
                block_type=BlockType.TABLE_ROW,
                raw_content=nl,
                content=nl,
                table_markdown=parent.table_markdown,
                parent_id=parent.block_id,
                parser_name=parent.parser_name,
                parser_version=parent.parser_version,
                metadata={**parent.metadata, "parent_block_id": parent.block_id, "row_index": i},
            )
            sub.enhanced_content = nl
            sub.processing_status = "enhanced"
            sub_blocks.append(sub)
        return sub_blocks

    # ── helpers ──

    @staticmethod
    def _detect_table(text: str) -> list[list[str]]:
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if any("|" in l for l in lines):
            rows = [[c.strip() for c in l.split("|") if c.strip()] for l in lines]
            return rows if len(rows) >= 2 else []
        if any("\t" in l for l in lines):
            rows = [[c.strip() for c in l.split("\t") if c.strip()] for l in lines]
            return rows if len(rows) >= 2 and TableModalProcessor._consistent(rows) else []
        spaced = [[c.strip() for c in re.split(r"\s{2,}", l) if c.strip()] for l in lines]
        spaced = [r for r in spaced if len(r) >= 3]
        return spaced if len(spaced) >= 2 and TableModalProcessor._consistent(spaced) else []

    @staticmethod
    def _consistent(rows: list[list[str]], tol: int = 1) -> bool:
        cols = [len(r) for r in rows]
        return max(cols) - min(cols) <= tol

    @staticmethod
    def _find_freq_columns(headers: list[str], data: list[list[str]]) -> list[str]:
        freq_keywords = ["frequency", "freq", "mhz", "ghz", "khz", "band", "频段", "频率"]
        cols = []
        for i, h in enumerate(headers):
            if any(kw in h.lower() for kw in freq_keywords):
                cols.append(h)
            else:
                # check if column values look like frequencies
                vals = [r[i] for r in data if i < len(r)]
                if any(re.search(r"\d+\s*(?:MHz|kHz|GHz|Hz)", str(v)) for v in vals):
                    cols.append(h)
        return cols

    @staticmethod
    def _find_region_columns(headers: list[str], data: list[list[str]]) -> list[str]:
        return [h for h in headers if "region" in h.lower() or "区域" in h]

    @staticmethod
    def _find_service_columns(headers: list[str], data: list[list[str]]) -> list[str]:
        svc_kw = ["service", "业务", "allocation", "分配"]
        return [h for h in headers if any(kw in h.lower() for kw in svc_kw)]
