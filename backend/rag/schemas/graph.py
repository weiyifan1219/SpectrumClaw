"""Knowledge graph schema — entities, relations, and extraction results."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal


# ── entity types ──
EntityType = Literal[
    "FrequencyBand", "RadioService", "Region", "Country", "Footnote",
    "Standard", "Organization", "DeviceType", "ApplicationScenario",
    "Document", "Section", "Page", "Table", "TableRow", "Image",
    "Chart", "Equation", "Variable", "Constraint", "EmissionType", "BandName",
]

# ── relation types ──
RelationType = Literal[
    "allocated_to", "applies_in", "limited_by", "belongs_to", "defined_by",
    "mentioned_in", "adjacent_to", "conflicts_with", "used_for",
    "contains", "located_on", "caption_of", "footnote_of",
    "derived_from", "visualizes", "explains", "has_variable",
    "constrains", "same_as", "overlaps_with", "nearby_band",
]


@dataclass
class SpectrumEntity:
    name: str
    type: str  # EntityType
    evidence_block_id: str = ""
    confidence: float = 1.0
    extractor: str = "rule"  # rule | llm | table | vlm
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "type": self.type,
            "evidence_block_id": self.evidence_block_id,
            "confidence": self.confidence,
            "extractor": self.extractor,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict) -> SpectrumEntity:
        return cls(
            name=d.get("name", ""),
            type=d.get("type", "Unknown"),
            evidence_block_id=d.get("evidence_block_id", ""),
            confidence=d.get("confidence", 1.0),
            extractor=d.get("extractor", "rule"),
            metadata=d.get("metadata", {}),
        )


@dataclass
class SpectrumRelation:
    source: str
    relation: str  # RelationType
    target: str
    evidence_block_id: str = ""
    confidence: float = 1.0
    weight: float = 1.0
    extractor: str = "rule"
    doc_id: str = ""
    page_idx: int = 0
    source_path: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "relation": self.relation,
            "target": self.target,
            "evidence_block_id": self.evidence_block_id,
            "confidence": self.confidence,
            "weight": self.weight,
            "extractor": self.extractor,
            "doc_id": self.doc_id,
            "page_idx": self.page_idx,
            "source_path": self.source_path,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict) -> SpectrumRelation:
        return cls(
            source=d.get("source", ""),
            relation=d.get("relation", ""),
            target=d.get("target", ""),
            evidence_block_id=d.get("evidence_block_id", ""),
            confidence=d.get("confidence", 1.0),
            weight=d.get("weight", 1.0),
            extractor=d.get("extractor", "rule"),
            doc_id=d.get("doc_id", ""),
            page_idx=d.get("page_idx", 0),
            source_path=d.get("source_path", ""),
            created_at=d.get("created_at", ""),
            metadata=d.get("metadata", {}),
        )


@dataclass
class ExtractionResult:
    entities: list[SpectrumEntity] = field(default_factory=list)
    relations: list[SpectrumRelation] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "entities": [e.to_dict() for e in self.entities],
            "relations": [r.to_dict() for r in self.relations],
        }
