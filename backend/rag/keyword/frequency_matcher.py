"""FrequencyRangeMatcher — precise frequency matching with unit conversion and overlap detection."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class FrequencyRange:
    min_mhz: float
    max_mhz: float
    raw: str = ""
    alias: str | None = None  # S-band, C-band, etc.

    @classmethod
    def parse(cls, text: str) -> FrequencyRange | None:
        """Parse '2300-2400 MHz', '5.8 GHz', '700MHz' into a FrequencyRange."""
        text = text.strip()
        # range: XXX-YYY unit
        m = re.match(r"(\d+\.?\d*)\s*[-–]\s*(\d+\.?\d*)\s*(MHz|kHz|GHz|Hz)", text, re.IGNORECASE)
        if m:
            return cls(
                min_mhz=cls._to_mhz(float(m[1]), m[3]),
                max_mhz=cls._to_mhz(float(m[2]), m[3]),
                raw=text,
            )
        # single: XXX unit
        m = re.match(r"(\d+\.?\d*)\s*(MHz|kHz|GHz|Hz)", text, re.IGNORECASE)
        if m:
            v = cls._to_mhz(float(m[1]), m[2])
            return cls(min_mhz=v, max_mhz=v, raw=text)
        return None

    @staticmethod
    def _to_mhz(value: float, unit: str) -> float:
        u = unit.upper()
        if u == "GHZ":
            return value * 1000
        if u == "MHZ":
            return value
        if u == "KHZ":
            return value / 1000
        if u == "HZ":
            return value / 1_000_000
        return value

    @property
    def center_mhz(self) -> float:
        return (self.min_mhz + self.max_mhz) / 2

    def contains(self, other: FrequencyRange) -> bool:
        return self.min_mhz <= other.min_mhz and self.max_mhz >= other.max_mhz

    def overlaps(self, other: FrequencyRange) -> bool:
        return self.min_mhz <= other.max_mhz and self.max_mhz >= other.min_mhz

    def overlap_ratio(self, other: FrequencyRange) -> float:
        if not self.overlaps(other):
            return 0.0
        o_min = max(self.min_mhz, other.min_mhz)
        o_max = min(self.max_mhz, other.max_mhz)
        o_span = o_max - o_min
        # Point match: single frequency falls within a range → 0.5
        if o_span == 0 and (self.min_mhz != self.max_mhz or other.min_mhz != other.max_mhz):
            return 0.5
        self_span = self.max_mhz - self.min_mhz or 1
        return min(1.0, o_span / self_span)


class FrequencyRangeMatcher:
    """Match frequency ranges against text, supporting exact, contains, and overlap modes."""

    # band aliases
    BAND_ALIASES = {
        "s-band": (2000, 4000),
        "s band": (2000, 4000),
        "c-band": (4000, 8000),
        "c band": (4000, 8000),
        "x-band": (8000, 12000),
        "x band": (8000, 12000),
        "ku-band": (12000, 18000),
        "ku band": (12000, 18000),
        "k-band": (18000, 26500),
        "k band": (18000, 26500),
        "ka-band": (26500, 40000),
        "ka band": (26500, 40000),
        "vhf": (30, 300),
        "uhf": (300, 3000),
        "hf": (3, 30),
        "lf": (0.03, 0.3),
        "mf": (0.3, 3),
        "ehf": (30000, 300000),
        "shf": (3000, 30000),
    }

    def search(self, query: str, candidates: list[str],
               mode: str = "overlap") -> list[tuple[str, float]]:
        """Find text entries whose frequency ranges match the query range.

        Returns list of (text, score) pairs sorted by relevance.
        """
        query_range = FrequencyRange.parse(query)
        if query_range is None:
            # try band alias
            ql = query.lower()
            for alias, (l, h) in self.BAND_ALIASES.items():
                if alias in ql:
                    query_range = FrequencyRange(min_mhz=l, max_mhz=h, alias=alias)
                    break
        if query_range is None:
            return []

        scored = []
        for text in candidates:
            ranges = self._extract_ranges(text)
            if not ranges:
                continue
            best = 0.0
            for r in ranges:
                if mode == "exact":
                    if r.min_mhz == query_range.min_mhz and r.max_mhz == query_range.max_mhz:
                        best = 1.0
                        break
                elif mode == "contains":
                    if query_range.contains(r) or r.contains(query_range):
                        best = max(best, 0.8)
                elif mode == "overlap":
                    best = max(best, query_range.overlap_ratio(r))
            if best > 0:
                scored.append((text, best))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    def _extract_ranges(self, text: str) -> list[FrequencyRange]:
        pattern = re.compile(
            r"(\d+\.?\d*\s*[-–]\s*\d+\.?\d*\s*(?:MHz|kHz|GHz|Hz))|"
            r"(\d+\.?\d*\s*(?:MHz|kHz|GHz|Hz))",
            re.IGNORECASE,
        )
        ranges = []
        for m in pattern.findall(text):
            raw = m[0] or m[1]
            r = FrequencyRange.parse(raw)
            if r:
                ranges.append(r)
        return ranges
