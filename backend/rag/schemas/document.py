"""SpectrumDocument v2 — parsed document with block list and metadata."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .block import SpectrumContentBlock


@dataclass
class SpectrumDocument:
    doc_id: str
    filename: str
    source_path: str
    blocks: list[SpectrumContentBlock] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    parsed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # ── helpers ──

    def get_blocks_by_type(self, block_type: str) -> list[SpectrumContentBlock]:
        return [b for b in self.blocks if b.block_type == block_type]

    def get_blocks_by_page(self, page_idx: int) -> list[SpectrumContentBlock]:
        return [b for b in self.blocks if b.page_idx == page_idx]

    @property
    def block_count(self) -> int:
        return len(self.blocks)

    @property
    def page_count(self) -> int:
        if not self.blocks:
            return 0
        return max(b.page_idx for b in self.blocks)

    # ── serialization ──

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
        blocks_raw = d.get("blocks", [])
        # Auto-detect v1 vs v2 block format
        blocks = []
        for bd in blocks_raw:
            if "raw_content" in bd or "asset_path" in bd:
                blocks.append(SpectrumContentBlock.from_dict(bd))
            else:
                blocks.append(SpectrumContentBlock.from_v1_dict(bd))
        return cls(
            doc_id=d.get("doc_id", ""),
            filename=d.get("filename", ""),
            source_path=d.get("source_path", ""),
            blocks=blocks,
            metadata=d.get("metadata", {}),
            parsed_at=d.get("parsed_at", ""),
        )

    @classmethod
    def load(cls, parsed_dir: str | Path, doc_id: str) -> SpectrumDocument | None:
        """Load a parsed document from data/parsed/{doc_id}/content_list.json."""
        import json
        p = Path(parsed_dir) / doc_id / "content_list.json"
        if not p.exists():
            return None
        return cls.from_dict(json.loads(p.read_text()))

    def save(self, parsed_dir: str | Path, save_assets: bool = False):
        """Save document to data/parsed/{doc_id}/."""
        import json
        out = Path(parsed_dir) / self.doc_id
        out.mkdir(parents=True, exist_ok=True)
        # content_list.json
        (out / "content_list.json").write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2))
        # document.md
        md_parts = [f"# {self.filename}\n"]
        for b in self.blocks:
            prefix = {
                "table": "## Table", "image": "## Image",
                "equation": "## Equation", "footnote": "## Footnote",
                "title": "##", "text": "",
            }.get(b.block_type, "")
            if prefix:
                md_parts.append(f"\n{prefix} (p.{b.page_idx})\n")
            if b.caption:
                md_parts.append(f"> {b.caption[0]}\n")
            md_parts.append(f"{b.content}\n\n")
        (out / "document.md").write_text("".join(md_parts))
        # assets
        if save_assets:
            (out / "assets").mkdir(exist_ok=True)
            (out / "assets" / "images").mkdir(exist_ok=True)

    @staticmethod
    def make_doc_id(file_path: str) -> str:
        return hashlib.md5(file_path.encode()).hexdigest()[:12]
