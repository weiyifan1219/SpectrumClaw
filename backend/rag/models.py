"""Unified data structures for the RAG pipeline."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class SpectrumContentBlock:
    block_id: str
    doc_id: str
    source_path: str
    page_idx: int
    block_type: str  # text / table / image / equation / footnote / title
    content: str
    enhanced_content: str = ""
    caption: str | None = None
    section_path: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        doc_id: str,
        source_path: str,
        page_idx: int,
        block_type: str,
        content: str,
        caption: str | None = None,
        section_path: list[str] | None = None,
        metadata: dict | None = None,
    ) -> SpectrumContentBlock:
        return cls(
            block_id=str(uuid.uuid4())[:12],
            doc_id=doc_id,
            source_path=source_path,
            page_idx=page_idx,
            block_type=block_type,
            content=content,
            caption=caption,
            section_path=section_path or [],
            metadata=metadata or {},
        )

    def to_dict(self) -> dict:
        return {
            "block_id": self.block_id,
            "doc_id": self.doc_id,
            "source_path": self.source_path,
            "page_idx": self.page_idx,
            "block_type": self.block_type,
            "content": self.content,
            "enhanced_content": self.enhanced_content,
            "caption": self.caption,
            "section_path": self.section_path,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict) -> SpectrumContentBlock:
        return cls(
            block_id=d["block_id"],
            doc_id=d["doc_id"],
            source_path=d["source_path"],
            page_idx=d["page_idx"],
            block_type=d["block_type"],
            content=d["content"],
            enhanced_content=d.get("enhanced_content", ""),
            caption=d.get("caption"),
            section_path=d.get("section_path", []),
            metadata=d.get("metadata", {}),
        )


@dataclass
class SpectrumDocument:
    doc_id: str
    filename: str
    source_path: str
    blocks: list[SpectrumContentBlock] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    parsed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "doc_id": self.doc_id,
            "filename": self.filename,
            "source_path": self.source_path,
            "blocks": [b.to_dict() for b in self.blocks],
            "metadata": self.metadata,
            "parsed_at": self.parsed_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> SpectrumDocument:
        return cls(
            doc_id=d["doc_id"],
            filename=d["filename"],
            source_path=d["source_path"],
            blocks=[SpectrumContentBlock.from_dict(b) for b in d.get("blocks", [])],
            metadata=d.get("metadata", {}),
            parsed_at=d.get("parsed_at", ""),
        )
