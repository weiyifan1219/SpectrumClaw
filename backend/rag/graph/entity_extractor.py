"""Spectrum entity and relation extractor for knowledge graph construction.

Extracts: FrequencyBand, RadioService, Region, Country, Footnote,
Standard, Organization, and their relationships (allocated_to, applies_in, etc.)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class SpectrumEntity:
    name: str
    type: str  # FrequencyBand / RadioService / Region / Footnote / Standard / etc.
    evidence_block_id: str = ""
    confidence: float = 1.0

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "type": self.type,
            "evidence_block_id": self.evidence_block_id,
            "confidence": self.confidence,
        }


@dataclass
class SpectrumRelation:
    source: str
    relation: str
    target: str
    evidence_block_id: str = ""
    confidence: float = 1.0

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "relation": self.relation,
            "target": self.target,
            "evidence_block_id": self.evidence_block_id,
            "confidence": self.confidence,
        }


@dataclass
class ExtractionResult:
    entities: list[SpectrumEntity] = field(default_factory=list)
    relations: list[SpectrumRelation] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "entities": [e.to_dict() for e in self.entities],
            "relations": [r.to_dict() for r in self.relations],
        }


# ── relation types ──
ALLOCATED_TO = "allocated_to"
APPLIES_IN = "applies_in"
LIMITED_BY = "limited_by"
DEFINED_BY = "defined_by"
MENTIONED_IN = "mentioned_in"
ADJACENT_TO = "adjacent_to"
USED_FOR = "used_for"


class SpectrumEntityExtractor:
    """Rule-based spectrum entity and relation extractor.

    Processes enhanced_content from SpectrumContentBlocks and outputs
    structured entities and relationships for knowledge graph construction.
    """

    # ── entity patterns ──
    FREQ_BAND = re.compile(
        r"(\d{1,4}\s*[-–]\s*\d{1,4}\s*(?:MHz|kHz|GHz|Hz))",
        re.IGNORECASE,
    )
    FREQ_SINGLE = re.compile(
        r"(\d{2,5}\s*(?:MHz|kHz|GHz|Hz))\b",
        re.IGNORECASE,
    )
    REGION_REF = re.compile(r"(Region\s+[1-3])", re.IGNORECASE)
    # ITU-R Regions:
    #   1 — Europe, Africa, Middle East, N. Asia (former USSR)
    #   2 — The Americas & Greenland
    #   3 — Asia-Pacific (south of Russia), Australia, Oceania
    FOOTNOTE_REF = re.compile(r"\b(5\.\d{3}[A-Z]?)\b")
    STANDARD_REF = re.compile(
        r"(?:ITU-R|Rec\.)\s*(M|F|S|P|BO|BS|BT|RA|RS|SA|SF|SM|SNG|TF)\.?\s*(\d+[-\w]*)",
        re.IGNORECASE,
    )

    # ── service keywords → standardized names ──
    SERVICE_MAP = {
        "mobile": ("Mobile Service", ["mobile", "移动"]),
        "fixed": ("Fixed Service", ["fixed", "固定"]),
        "broadcasting": ("Broadcasting Service", ["broadcasting", "广播"]),
        "broadcasting-satellite": ("Broadcasting-Satellite Service", ["broadcasting-satellite", "卫星广播"]),
        "fixed-satellite": ("Fixed-Satellite Service", ["fixed-satellite", "卫星固定"]),
        "mobile-satellite": ("Mobile-Satellite Service", ["mobile-satellite", "卫星移动"]),
        "radiolocation": ("Radiolocation Service", ["radiolocation", "无线电定位"]),
        "radionavigation": ("Radionavigation Service", ["radionavigation", "无线电导航"]),
        "aeronautical": ("Aeronautical Mobile Service", ["aeronautical", "航空"]),
        "maritime": ("Maritime Mobile Service", ["maritime", "海事"]),
        "amateur": ("Amateur Service", ["amateur", "业余"]),
        "meteorological": ("Meteorological Service", ["meteorological", "气象"]),
        "radio astronomy": ("Radio Astronomy Service", ["radio astronomy", "射电天文"]),
        "space research": ("Space Research Service", ["space research", "空间研究"]),
        "earth exploration": ("Earth Exploration-Satellite Service", ["earth exploration", "地球探测"]),
    }

    # ── allocation keywords for relation extraction ──
    ALLOCATION_KEYWORDS = [
        "allocated", "allocation", "分配", "划分",
        "primary", "次要", "secondary",
        "designated", "designation", "designated for",
    ]

    def extract(self, text: str, block_id: str = "") -> ExtractionResult:
        result = ExtractionResult()

        # Extract frequency bands
        band_ranges = set(self.FREQ_BAND.findall(text))
        single_freqs = set(self.FREQ_SINGLE.findall(text))
        # Remove single freqs that are part of an already-captured range
        for freq_range in list(band_ranges):
            range_text = freq_range.replace(" ", "").lower()
            for sf in list(single_freqs):
                if sf.replace(" ", "").lower() in range_text:
                    single_freqs.discard(sf)
        freq_bands = band_ranges | single_freqs
        for fb in freq_bands:
            result.entities.append(SpectrumEntity(
                name=fb, type="FrequencyBand", evidence_block_id=block_id,
            ))

        # Extract regions
        for m in set(self.REGION_REF.findall(text)):
            result.entities.append(SpectrumEntity(
                name=m, type="Region", evidence_block_id=block_id,
            ))

        # Extract footnotes
        for m in set(self.FOOTNOTE_REF.findall(text)):
            result.entities.append(SpectrumEntity(
                name=m, type="Footnote", evidence_block_id=block_id,
            ))

        # Extract standards
        for m in self.STANDARD_REF.findall(text):
            std_name = f"ITU-R {m[0]}.{m[1]}"
            result.entities.append(SpectrumEntity(
                name=std_name, type="Standard", evidence_block_id=block_id,
            ))

        # Extract services
        text_lower = text.lower()
        for svc_key, (svc_name, keywords) in self.SERVICE_MAP.items():
            if any(kw in text_lower for kw in keywords):
                result.entities.append(SpectrumEntity(
                    name=svc_name, type="RadioService", evidence_block_id=block_id,
                ))

        # Extract relations: FrequencyBand → allocated_to → RadioService
        if any(kw in text_lower for kw in self.ALLOCATION_KEYWORDS):
            freqs = [e for e in result.entities if e.type == "FrequencyBand"]
            svcs = [e for e in result.entities if e.type == "RadioService"]
            regions = [e for e in result.entities if e.type == "Region"]
            footnotes = [e for e in result.entities if e.type == "Footnote"]

            for freq in freqs:
                for svc in svcs:
                    result.relations.append(SpectrumRelation(
                        source=freq.name, relation=ALLOCATED_TO,
                        target=svc.name, evidence_block_id=block_id,
                    ))
                for region in regions:
                    result.relations.append(SpectrumRelation(
                        source=freq.name, relation=APPLIES_IN,
                        target=region.name, evidence_block_id=block_id,
                    ))
                for fn in footnotes:
                    result.relations.append(SpectrumRelation(
                        source=freq.name, relation=LIMITED_BY,
                        target=fn.name, evidence_block_id=block_id,
                    ))

        return result
