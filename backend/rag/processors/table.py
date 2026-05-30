"""TableModalProcessor — structured table → NL, row-level sub-blocks, entity extraction."""

from __future__ import annotations

import re

from ..schemas.block import SpectrumContentBlock, BlockType
from ..context.builder import BlockContext


class TableModalProcessor:
    """Detect tables, convert to markdown + natural language, create row sub-blocks.

    Each row becomes a sub-block linked via parent_id for independent retrieval.
    """

    name = "table_modal"

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
        md_lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
        for row in data[:50]:
            padded = row + [""] * (len(headers) - len(row))
            md_lines.append("| " + " | ".join(padded) + " |")
        block.table_markdown = "\n".join(md_lines)

        # build NL description
        caption = " ".join(block.caption) if block.caption else "Table"
        nl_parts = [f"{caption}. Columns: {', '.join(headers)}."]
        for i, row in enumerate(data[:40]):
            row_desc = []
            for h, v in zip(headers, row):
                if v and v not in ("-", "—", "N/A", "", "/"):
                    row_desc.append(f"{h}: {v}")
            if row_desc:
                nl_parts.append(f"Row {i + 1}: {'; '.join(row_desc)}.")

        block.enhanced_content = " ".join(nl_parts)
        block.table_rows = [{h: r[i] if i < len(r) else "" for i, h in enumerate(headers)}
                            for r in data]
        block.processing_status = "enhanced"
        block.metadata["table_headers"] = headers
        block.metadata["row_count"] = len(data)
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
                metadata={"parent_block_id": parent.block_id, "row_index": i},
            )
            sub.enhanced_content = nl
            sub.processing_status = "enhanced"
            sub_blocks.append(sub)
        return sub_blocks

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
