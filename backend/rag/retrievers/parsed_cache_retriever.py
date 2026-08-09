"""Dependency-light lexical retrieval over the existing parsed document cache.

This fallback is used only when Chroma/BM25 dependencies are unavailable or
return no candidates. It reads the source-grounded ``content_list.json`` files
and preserves block/page metadata for the normal citation packer.
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any

from ..paths import KB_RAW_DIR, PARSED_DIR


_TOKEN_RE = re.compile(r"[a-z][a-z0-9.-]{1,}|\d+(?:\.\d+)?", re.IGNORECASE)
_RANGE_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*[-–—]\s*(\d+(?:\.\d+)?)\s*(ghz|mhz|khz|hz)",
    re.IGNORECASE,
)
_THOUSANDS_SPACE_RE = re.compile(r"(?<=\d)[\s\u00a0]+(?=\d{3}(?:\D|$))")
_STOPWORDS = {
    "the", "and", "for", "with", "from", "into", "what", "which", "that",
    "this", "are", "use", "using", "service", "frequency", "band", "scene",
    "emitter", "power", "dbm", "mhz", "ghz", "unspecified", "target",
}
_DOMAIN_EXPANSIONS = {
    "频率划分": ("allocation", "allocated"),
    "分配": ("allocation", "allocated"),
    "主要业务": ("primary",),
    "次要业务": ("secondary",),
    "脚注": ("footnote",),
    "协调": ("coordination", "coordinate"),
    "保护": ("protection", "protect"),
    "干扰": ("interference", "interfering"),
    "移动业务": ("mobile",),
    "固定业务": ("fixed",),
    "卫星": ("satellite",),
    "航空": ("aeronautical",),
    "海上": ("maritime",),
    "射电天文": ("radio astronomy", "astronomy"),
}


class ParsedCacheRetriever:
    """Cached lexical search over parsed blocks without optional ML packages."""

    def __init__(self, parsed_dir: Path | str = PARSED_DIR) -> None:
        self.parsed_dir = Path(parsed_dir)
        self._blocks: list[dict[str, Any]] | None = None
        self._lock = threading.RLock()

    def is_available(self) -> bool:
        return self.parsed_dir.is_dir() and any(self.parsed_dir.glob("*/content_list.json"))

    def retrieve(self, query: str, top_k: int = 12) -> list[dict[str, Any]]:
        query_text = _normalize(query)
        query_terms = _query_terms(query_text)
        query_range = _RANGE_RE.search(query_text)
        scored: list[tuple[float, dict[str, Any]]] = []

        for block in self._load_blocks():
            normalized = block["normalized"]
            raw_score = 0.0
            matched_terms = 0
            for term, weight in query_terms.items():
                if term in normalized:
                    raw_score += weight
                    matched_terms += 1

            if query_range:
                low, high, unit = query_range.groups()
                exact_range = f"{low}-{high} {unit}".lower()
                compact_range = f"{low}-{high}{unit}".lower()
                compact_text = normalized.replace(" ", "")
                if exact_range in normalized or compact_range in compact_text:
                    raw_score += 8.0
                elif low in normalized and high in normalized and unit.lower() in normalized:
                    raw_score += 4.0

            block_type = block["metadata"].get("block_type", "")
            if raw_score > 0 and block_type in {"table", "footnote"}:
                raw_score += 0.8
            source = block["metadata"].get("source_path", "")
            if raw_score > 0 and ("R-REC" in source or "R-REP" in source):
                raw_score += 0.4

            # Require either a strong frequency match or several domain terms.
            if raw_score < 2.5 or matched_terms == 0:
                continue
            relevance = min(0.95, 0.25 + (raw_score / (raw_score + 5.0)) * 0.72)
            scored.append((relevance, block))

        scored.sort(key=lambda item: item[0], reverse=True)
        results = []
        for relevance, block in scored[:max(1, top_k)]:
            results.append({
                "block_id": block["block_id"],
                "text": block["text"],
                "metadata": dict(block["metadata"]),
                "score": round(relevance, 4),
            })
        return results

    def _load_blocks(self) -> list[dict[str, Any]]:
        with self._lock:
            if self._blocks is not None:
                return self._blocks

            blocks: list[dict[str, Any]] = []
            for cache_file in sorted(self.parsed_dir.glob("*/content_list.json")):
                try:
                    payload = json.loads(cache_file.read_text(encoding="utf-8"))
                except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if not isinstance(payload, list):
                    continue
                for index, item in enumerate(payload):
                    if not isinstance(item, dict):
                        continue
                    text = str(item.get("content") or item.get("enhanced_content") or "").strip()
                    if len(text) < 24:
                        continue
                    source = str(item.get("source_path") or "")
                    source_name = Path(source).name
                    local_source = KB_RAW_DIR / source_name
                    if source_name and local_source.is_file():
                        source = str(local_source)
                    metadata = {
                        "source_path": source,
                        "page_idx": item.get("pdf_page", item.get("page_idx", "?")),
                        "pdf_page": item.get("pdf_page", item.get("page_idx", "?")),
                        "block_type": str(item.get("block_type") or "text"),
                        "doc_id": str(item.get("doc_id") or cache_file.parent.name),
                        "text": text[:2000],
                        "retrieval_backend": "parsed_cache_lexical",
                    }
                    blocks.append({
                        "block_id": str(item.get("block_id") or f"{cache_file.parent.name}-{index}"),
                        "text": text,
                        "normalized": _normalize(text),
                        "metadata": metadata,
                    })
            self._blocks = blocks
            return blocks


def _normalize(text: str) -> str:
    normalized = str(text or "").lower().replace("−", "-").replace("–", "-").replace("—", "-")
    previous = None
    while previous != normalized:
        previous = normalized
        normalized = _THOUSANDS_SPACE_RE.sub("", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _query_terms(query: str) -> dict[str, float]:
    terms: dict[str, float] = {}
    for token in _TOKEN_RE.findall(query):
        token = token.lower().strip(".-")
        if len(token) < 2 or token in _STOPWORDS:
            continue
        if token.isdigit() or re.fullmatch(r"\d+(?:\.\d+)?", token):
            terms[token] = max(terms.get(token, 0.0), 2.5)
        elif token in {"mobile", "fixed", "satellite", "aeronautical", "maritime", "primary", "secondary"}:
            terms[token] = max(terms.get(token, 0.0), 1.6)
        else:
            terms[token] = max(terms.get(token, 0.0), 1.0)
    for chinese, expansions in _DOMAIN_EXPANSIONS.items():
        if chinese in query:
            for expansion in expansions:
                terms[expansion] = max(terms.get(expansion, 0.0), 1.4)
    return terms
