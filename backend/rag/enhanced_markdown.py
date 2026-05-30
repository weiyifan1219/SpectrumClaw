"""Enhanced Markdown converter — multimodal content rendering.

Aligned with RAG-Anything's enhanced_markdown.py.
Converts parsed documents to rich markdown with embedded images, tables, and equations.
"""

from __future__ import annotations

from pathlib import Path

from .schemas.document import SpectrumDocument
from .schemas.block import SpectrumContentBlock


def document_to_enhanced_markdown(
    doc: SpectrumDocument,
    include_images: bool = True,
    include_tables: bool = True,
    include_equations: bool = True,
) -> str:
    """Convert a SpectrumDocument to rich markdown with multimodal content embedded.

    Matches RAG-Anything's enhanced markdown rendering pattern.
    """
    lines = [f"# {doc.filename}\n"]

    current_page = 0
    for block in doc.blocks:
        if block.page_idx != current_page:
            current_page = block.page_idx
            lines.append(f"\n---\n## Page {current_page}\n")

        bt = block.block_type

        if bt in ("text", "title"):
            if bt == "title":
                lines.append(f"### {block.content}\n")
            else:
                lines.append(f"{block.content}\n\n")

        elif bt == "table" and include_tables:
            caption = " ".join(block.caption) if block.caption else "Table"
            lines.append(f"**{caption}** (p.{block.page_idx})\n")
            if block.table_markdown:
                lines.append(block.table_markdown + "\n")
            elif block.enhanced_content:
                lines.append(f"> {block.enhanced_content}\n")
            lines.append("")

        elif bt in ("image", "chart") and include_images:
            caption = " ".join(block.caption) if block.caption else "Image"
            lines.append(f"**Figure: {caption}** (p.{block.page_idx})\n")
            if block.asset_path:
                rel = _relative_path(block.asset_path)
                lines.append(f"![{caption}]({rel})\n")
            if block.modality_summary:
                lines.append(f"> {block.modality_summary}\n")
            lines.append("")

        elif bt == "equation" and include_equations:
            caption = " ".join(block.caption) if block.caption else "Equation"
            lines.append(f"**{caption}** (p.{block.page_idx})\n")
            if block.latex:
                lines.append(f"$$\n{block.latex}\n$$\n")
            if block.modality_summary:
                lines.append(f"> {block.modality_summary}\n")
            lines.append("")

        elif bt == "footnote":
            lines.append(f"> **Footnote:** {block.content}\n\n")

        else:
            lines.append(f"{block.content}\n\n")

    return "".join(lines)


def _relative_path(asset_path: str) -> str:
    try:
        return str(Path(asset_path).relative_to(Path.cwd()))
    except ValueError:
        return asset_path
