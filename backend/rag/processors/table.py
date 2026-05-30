"""Table processor — convert table content to natural language descriptions."""

from __future__ import annotations

import re

from ..models import SpectrumContentBlock


class TableProcessor:
    """Detect and convert tabular content into semantic natural language.

    Supports pipe-delimited, tab-delimited, and space-aligned tables commonly
    found in ITU-R spectrum allocation documents.
    """

    def process(self, block: SpectrumContentBlock) -> SpectrumContentBlock:
        text = block.content
        rows = self._detect_table(text)
        if not rows or len(rows) < 2:
            block.enhanced_content = text
            return block

        description = self._rows_to_description(rows, block.caption)
        block.enhanced_content = description
        block.metadata["table_rows"] = len(rows)
        block.metadata["table_headers"] = rows[0] if rows else []
        return block

    def _detect_table(self, text: str) -> list[list[str]]:
        """Try to parse text as a table."""
        lines = [l.strip() for l in text.split("\n") if l.strip()]

        # Pipe-delimited
        if any("|" in l for l in lines):
            rows = []
            for line in lines:
                cells = [c.strip() for c in line.split("|") if c.strip()]
                if cells:
                    rows.append(cells)
            if len(rows) >= 2:
                return rows

        # Tab-delimited
        if any("\t" in l for l in lines):
            rows = [[c.strip() for c in l.split("\t") if c.strip()] for l in lines]
            rows = [r for r in rows if r]
            if len(rows) >= 2 and self._consistent_cols(rows):
                return rows

        # Space-aligned (ITU-style): at least 3 columns, lines with multiple 2+ space gaps
        space_rows = []
        for line in lines:
            cells = re.split(r"\s{2,}", line)
            cells = [c.strip() for c in cells if c.strip()]
            if len(cells) >= 3:
                space_rows.append(cells)
        if len(space_rows) >= 2 and self._consistent_cols(space_rows):
            return space_rows

        return []

    @staticmethod
    def _consistent_cols(rows: list[list[str]], tolerance: int = 1) -> bool:
        if not rows:
            return False
        col_counts = [len(r) for r in rows]
        return max(col_counts) - min(col_counts) <= tolerance

    def _rows_to_description(self, rows: list[list[str]], caption: str | None) -> str:
        headers = rows[0]
        data = rows[1:]

        parts = []
        if caption:
            parts.append(f"Table: {caption}")

        parts.append(f"Columns: {', '.join(headers)}.")

        for i, row in enumerate(data[:30]):  # cap at 30 rows
            row_desc_parts = []
            for h, v in zip(headers, row):
                if v and v not in ("-", "—", "N/A", ""):
                    row_desc_parts.append(f"{h}: {v}")
            if row_desc_parts:
                parts.append(f"Row {i + 1}: {'; '.join(row_desc_parts)}.")

        return " ".join(parts)
