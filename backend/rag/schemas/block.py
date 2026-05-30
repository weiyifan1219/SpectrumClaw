"""SpectrumContentBlock v2 — multimodal content block with VLM-ready asset paths."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timezone


class BlockType(str, Enum):
    TEXT = "text"
    TITLE = "title"
    TABLE = "table"
    TABLE_ROW = "table_row"
    IMAGE = "image"
    EQUATION = "equation"
    FOOTNOTE = "footnote"
    CHART = "chart"
    CODE = "code"
    GENERIC = "generic"


@dataclass
class SpectrumContentBlock:
    """v2: multimodal content block with parser provenance, asset tracking, and entity linkage.

    Backwards-compatible with v1: old `content` and `caption` fields preserved.
    """

    block_id: str
    doc_id: str
    source_path: str
    page_idx: int
    block_type: str  # from BlockType enum

    # ── content layers ──
    raw_content: str = ""             # original extracted text
    content: str = ""                 # cleaned text (v1 compat)
    enhanced_content: str = ""        # semantic enrichment for embedding
    modality_summary: str | None = None  # short description of non-text modalities

    # ── captions & footnotes ──
    caption: list[str] = field(default_factory=list)
    footnote: list[str] = field(default_factory=list)
    section_path: list[str] = field(default_factory=list)

    # ── layout ──
    bbox: list[float] | None = None  # [x1, y1, x2, y2] in page coords

    # ── multimodal assets ──
    asset_path: str | None = None        # path to saved image/asset
    latex: str | None = None             # LaTeX source (equations)
    table_markdown: str | None = None    # markdown table representation
    table_rows: list[dict] | None = None # [{header: value, ...}, ...]
    parent_id: str | None = None         # parent block (e.g., table for table_row)

    # ── entities & relations extracted at parse time ──
    entities: list[dict] = field(default_factory=list)
    relations: list[dict] = field(default_factory=list)

    # ── provenance ──
    content_hash: str = ""
    parser_name: str = "unknown"
    parser_version: str = "0.0.0"
    processing_status: str = "raw"  # raw | processed | enhanced | indexed
    confidence: float = 1.0

    # ── general metadata ──
    metadata: dict = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        doc_id: str,
        source_path: str,
        page_idx: int,
        block_type: str,
        raw_content: str = "",
        *,
        content: str = "",
        caption: list[str] | None = None,
        section_path: list[str] | None = None,
        bbox: list[float] | None = None,
        asset_path: str | None = None,
        latex: str | None = None,
        table_markdown: str | None = None,
        parent_id: str | None = None,
        parser_name: str = "unknown",
        parser_version: str = "0.0.0",
        confidence: float = 1.0,
        metadata: dict | None = None,
    ) -> SpectrumContentBlock:
        bid = str(uuid.uuid4())[:12]
        raw = raw_content or content
        return cls(
            block_id=bid,
            doc_id=doc_id,
            source_path=source_path,
            page_idx=page_idx,
            block_type=block_type,
            raw_content=raw,
            content=content or raw,
            caption=caption or [],
            section_path=section_path or [],
            bbox=bbox,
            asset_path=asset_path,
            latex=latex,
            table_markdown=table_markdown,
            parent_id=parent_id,
            parser_name=parser_name,
            parser_version=parser_version,
            confidence=confidence,
            metadata=metadata or {},
            content_hash=hashlib.md5(raw.encode()).hexdigest()[:16] if raw else "",
        )

    # ── v1 compat ──
    @property
    def _v1_caption(self) -> str | None:
        return self.caption[0] if self.caption else None

    def to_dict(self) -> dict:
        return {
            "block_id": self.block_id,
            "doc_id": self.doc_id,
            "source_path": self.source_path,
            "page_idx": self.page_idx,
            "block_type": self.block_type,
            "type": self.block_type,
            "raw_content": self.raw_content,
            "content": self.content,
            "enhanced_content": self.enhanced_content,
            "modality_summary": self.modality_summary,
            "caption": self.caption,
            "footnote": self.footnote,
            "section_path": self.section_path,
            "bbox": self.bbox,
            "asset_path": self.asset_path,
            "latex": self.latex,
            "table_markdown": self.table_markdown,
            "table_rows": self.table_rows,
            "parent_id": self.parent_id,
            "entities": self.entities,
            "relations": self.relations,
            "content_hash": self.content_hash,
            "parser_name": self.parser_name,
            "parser_version": self.parser_version,
            "processing_status": self.processing_status,
            "confidence": self.confidence,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict) -> SpectrumContentBlock:
        return cls(
            block_id=d.get("block_id", ""),
            doc_id=d.get("doc_id", ""),
            source_path=d.get("source_path", ""),
            page_idx=d.get("page_idx", 0),
            block_type=d.get("block_type") or d.get("type", "text"),
            raw_content=d.get("raw_content", ""),
            content=d.get("content", d.get("raw_content", "")),
            enhanced_content=d.get("enhanced_content", ""),
            modality_summary=d.get("modality_summary"),
            caption=d.get("caption") or ([d["caption"]] if isinstance(d.get("caption"), str) and d["caption"] else []),
            footnote=d.get("footnote", []),
            section_path=d.get("section_path", []),
            bbox=d.get("bbox"),
            asset_path=d.get("asset_path"),
            latex=d.get("latex"),
            table_markdown=d.get("table_markdown"),
            table_rows=d.get("table_rows"),
            parent_id=d.get("parent_id"),
            entities=d.get("entities", []),
            relations=d.get("relations", []),
            content_hash=d.get("content_hash", ""),
            parser_name=d.get("parser_name", "unknown"),
            parser_version=d.get("parser_version", "0.0.0"),
            processing_status=d.get("processing_status", "raw"),
            confidence=d.get("confidence", 1.0),
            metadata=d.get("metadata", {}),
        )

    @classmethod
    def from_v1_dict(cls, d: dict) -> SpectrumContentBlock:
        """Upgrade a v1 block dict to v2. Preserves all old fields."""
        return cls(
            block_id=d.get("block_id", ""),
            doc_id=d.get("doc_id", ""),
            source_path=d.get("source_path", ""),
            page_idx=d.get("page_idx", 0),
            block_type=d.get("block_type", "text"),
            raw_content=d.get("content", ""),
            content=d.get("content", ""),
            enhanced_content=d.get("enhanced_content", ""),
            caption=[d["caption"]] if isinstance(d.get("caption"), str) and d["caption"] else [],
            section_path=d.get("section_path", []),
            parser_name=d.get("metadata", {}).get("parser", "pypdf"),
            parser_version="1.0.0",
            metadata=d.get("metadata", {}),
            content_hash=hashlib.md5(d.get("content", "").encode()).hexdigest()[:16],
        )
