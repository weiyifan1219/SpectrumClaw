"""Spectrum query analyzer — extract domain entities from user questions."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class QueryInfo:
    frequency_range: str | None = None
    region: str | None = None
    country: str | None = None
    radio_service: str | None = None
    standard: str | None = None
    footnote: str | None = None
    intent: str = "general"
    raw_query: str = ""

    def to_dict(self) -> dict:
        return {
            "frequency_range": self.frequency_range,
            "region": self.region,
            "country": self.country,
            "radio_service": self.radio_service,
            "standard": self.standard,
            "footnote": self.footnote,
            "intent": self.intent,
        }


class SpectrumQueryAnalyzer:
    """Rule-based spectrum query entity extractor.

    Extracts: frequency_range, region, radio_service, standard, footnote, intent.
    """

    # ── patterns ──
    FREQ_RANGE = re.compile(
        r"(\d{1,4}\s*[-–]\s*\d{1,4}\s*(?:MHz|kHz|GHz|Hz))|"
        r"(\d{2,5}\s*(?:MHz|kHz|GHz|Hz))",
        re.IGNORECASE,
    )
    REGION = re.compile(r"(Region\s+[1-4])", re.IGNORECASE)
    COUNTRY = re.compile(
        r"\b(China|USA?|Japan|Korea|Germany|France|UK|"
        r"India|Brazil|Russia|Canada|Australia)\b",
        re.IGNORECASE,
    )
    FOOTNOTE = re.compile(r"(?:footnote|脚注|note)\s*(5\.\d{3}[A-Z]?)", re.IGNORECASE)
    FOOTNOTE_STANDALONE = re.compile(r"\b(5\.\d{3}[A-Z]?)\b")
    STANDARD = re.compile(
        r"(ITU-R\s+(?:M|F|S|P|BO|BS|BT|RA|RS|SA|SF|SM|SNG|TF)\.?\s*\d+[-\w]*)",
        re.IGNORECASE,
    )

    SERVICE_KEYWORDS = {
        "Mobile": ["mobile", "移动"],
        "Fixed": ["fixed", "固定"],
        "Broadcasting": ["broadcasting", "广播"],
        "Satellite": ["satellite", "卫星"],
        "Radiolocation": ["radiolocation", "无线电定位"],
        "Radionavigation": ["radionavigation", "无线电导航"],
        "Amateur": ["amateur", "业余"],
        "Aeronautical": ["aeronautical", "航空"],
        "Maritime": ["maritime", "海事"],
        "Meteorological": ["meteorological", "气象"],
        "Radio Astronomy": ["radio astronomy", "射电天文"],
        "Space Research": ["space research", "空间研究"],
        "Earth Exploration": ["earth exploration", "地球探测"],
    }

    INTENT_KEYWORDS = {
        "allocation_check": ["分配", "allocated", "能不能用", "can use", "可用于", "allocation"],
        "footnote_lookup": ["脚注", "footnote", "限制", "limitation", "condition"],
        "standard_lookup": ["标准", "standard", "recommendation", "建议书"],
        "interference_check": ["干扰", "interference", "protection", "保护"],
        "band_plan": ["频段划分", "band plan", "allocation table", "分配表"],
    }

    def analyze(self, query: str) -> QueryInfo:
        info = QueryInfo(raw_query=query)

        freq_matches = self.FREQ_RANGE.findall(query)
        if freq_matches:
            freqs = []
            for m in freq_matches:
                s = m[0] or m[1]
                if s:
                    freqs.append(s)
            info.frequency_range = ", ".join(freqs[:3])

        region_match = self.REGION.search(query)
        if region_match:
            info.region = region_match.group(0)

        country_match = self.COUNTRY.search(query)
        if country_match:
            info.country = country_match.group(0)

        fn_match = self.FOOTNOTE.search(query)
        if fn_match:
            info.footnote = fn_match.group(0)
        else:
            fn_standalone = self.FOOTNOTE_STANDALONE.findall(query)
            if fn_standalone:
                info.footnote = ", ".join(fn_standalone)

        std_match = self.STANDARD.search(query)
        if std_match:
            info.standard = std_match.group(0)

        query_lower = query.lower()
        for svc_name, keywords in self.SERVICE_KEYWORDS.items():
            if any(kw in query_lower for kw in keywords):
                info.radio_service = svc_name
                break

        for intent_name, keywords in self.INTENT_KEYWORDS.items():
            if any(kw in query_lower for kw in keywords):
                info.intent = intent_name
                break

        return info
