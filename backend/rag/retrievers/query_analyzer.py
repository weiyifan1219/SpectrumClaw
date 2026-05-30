"""Spectrum query analyzer — extract domain entities from user questions."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class QueryInfo:
    frequency_range: str | None = None
    region: str | None = None
    region_description: str | None = None
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
            "region_description": self.region_description,
            "country": self.country,
            "radio_service": self.radio_service,
            "standard": self.standard,
            "footnote": self.footnote,
            "intent": self.intent,
        }


# ITU-R Radio Regulations — country → region mapping
# Region 1: Europe, Africa, Middle East, former USSR
# Region 2: The Americas & Greenland
# Region 3: Asia-Pacific, Australia, Oceania
COUNTRY_TO_REGION: dict[str, tuple[str, str]] = {
    # Region 1
    "uk": ("Region 1", "Europe, Africa, Middle East, N. Asia"),
    "germany": ("Region 1", "Europe, Africa, Middle East, N. Asia"),
    "france": ("Region 1", "Europe, Africa, Middle East, N. Asia"),
    "russia": ("Region 1", "Europe, Africa, Middle East, N. Asia"),
    "saudi arabia": ("Region 1", "Europe, Africa, Middle East, N. Asia"),
    "uae": ("Region 1", "Europe, Africa, Middle East, N. Asia"),
    "turkey": ("Region 1", "Europe, Africa, Middle East, N. Asia"),
    "英国": ("Region 1", "Europe, Africa, Middle East, N. Asia"),
    "德国": ("Region 1", "Europe, Africa, Middle East, N. Asia"),
    "法国": ("Region 1", "Europe, Africa, Middle East, N. Asia"),
    "俄罗斯": ("Region 1", "Europe, Africa, Middle East, N. Asia"),
    "沙特": ("Region 1", "Europe, Africa, Middle East, N. Asia"),
    "阿联酋": ("Region 1", "Europe, Africa, Middle East, N. Asia"),
    "土耳其": ("Region 1", "Europe, Africa, Middle East, N. Asia"),
    # Region 2
    "usa": ("Region 2", "The Americas & Greenland"),
    "us": ("Region 2", "The Americas & Greenland"),
    "canada": ("Region 2", "The Americas & Greenland"),
    "brazil": ("Region 2", "The Americas & Greenland"),
    "mexico": ("Region 2", "The Americas & Greenland"),
    "argentina": ("Region 2", "The Americas & Greenland"),
    "加拿大": ("Region 2", "The Americas & Greenland"),
    "巴西": ("Region 2", "The Americas & Greenland"),
    "墨西哥": ("Region 2", "The Americas & Greenland"),
    "阿根廷": ("Region 2", "The Americas & Greenland"),
    # Region 3
    "china": ("Region 3", "Asia-Pacific, Australia, Oceania"),
    "japan": ("Region 3", "Asia-Pacific, Australia, Oceania"),
    "korea": ("Region 3", "Asia-Pacific, Australia, Oceania"),
    "india": ("Region 3", "Asia-Pacific, Australia, Oceania"),
    "australia": ("Region 3", "Asia-Pacific, Australia, Oceania"),
    "singapore": ("Region 3", "Asia-Pacific, Australia, Oceania"),
    "indonesia": ("Region 3", "Asia-Pacific, Australia, Oceania"),
    "thailand": ("Region 3", "Asia-Pacific, Australia, Oceania"),
    "vietnam": ("Region 3", "Asia-Pacific, Australia, Oceania"),
    "中国": ("Region 3", "Asia-Pacific, Australia, Oceania"),
    "日本": ("Region 3", "Asia-Pacific, Australia, Oceania"),
    "韩国": ("Region 3", "Asia-Pacific, Australia, Oceania"),
    "印度": ("Region 3", "Asia-Pacific, Australia, Oceania"),
    "澳大利亚": ("Region 3", "Asia-Pacific, Australia, Oceania"),
    "新加坡": ("Region 3", "Asia-Pacific, Australia, Oceania"),
    "印尼": ("Region 3", "Asia-Pacific, Australia, Oceania"),
    "泰国": ("Region 3", "Asia-Pacific, Australia, Oceania"),
    "越南": ("Region 3", "Asia-Pacific, Australia, Oceania"),
}

REGION_DESCRIPTIONS = {
    "Region 1": "Europe, Africa, Middle East, N. Asia (former USSR)",
    "Region 2": "The Americas & Greenland",
    "Region 3": "Asia-Pacific, Australia, Oceania",
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
    REGION = re.compile(r"(Region\s+[1-3])", re.IGNORECASE)
    # ITU Radio Regulations define exactly 3 regions:
    #   Region 1 — Europe, Africa, Middle East, former USSR (incl. Mongolia)
    #   Region 2 — The Americas (North/Central/South) & Greenland
    #   Region 3 — Asia (south of Russia), Australia, New Zealand, Oceania
    # English country names (with word boundaries)
    COUNTRY_EN = re.compile(
        r"\b(China|USA?|Japan|Korea|Germany|France|UK|"
        r"India|Brazil|Russia|Canada|Australia|"
        r"Singapore|Indonesia|Thailand|Vietnam|Saudi Arabia|UAE|Turkey|Mexico|Argentina)\b",
        re.IGNORECASE,
    )
    # Chinese country names (no word boundaries — CJK doesn't use them)
    COUNTRY_CN = re.compile(
        r"(中国|日本|韩国|德国|法国|英国|印度|巴西|俄罗斯|加拿大|澳大利亚|"
        r"新加坡|印尼|泰国|越南|沙特|阿联酋|土耳其|墨西哥|阿根廷)"
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
            info.region_description = REGION_DESCRIPTIONS.get(info.region)

        country_match = self.COUNTRY_EN.search(query)
        if not country_match:
            country_match = self.COUNTRY_CN.search(query)
        if country_match:
            info.country = country_match.group(0)
            country_key = info.country.lower()
            if country_key in COUNTRY_TO_REGION:
                mapped_region, mapped_desc = COUNTRY_TO_REGION[country_key]
                if not info.region:
                    info.region = mapped_region
                    info.region_description = mapped_desc

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
