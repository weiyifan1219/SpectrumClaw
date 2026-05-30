"""Reranker — rule-based priority scoring for spectrum retrieval results."""

from __future__ import annotations

from .query_analyzer import QueryInfo


class Reranker:
    """Rule-based reranker that scores results by spectrum-domain relevance.

    Priority (descending):
      1. Exact frequency range match (+0.30)
      2. Exact region match (+0.20)
      3. Exact radio service match (+0.20)
      4. Graph entity match (+0.15)
      5. Table / footnote block type priority (+0.10~0.15)
      6. Exact standard/Footnote match (+0.15)
      7. Source authority (+0.05)
    """

    def rerank(
        self,
        results: list[dict],
        query_info: QueryInfo,
        graph_results: list[dict] | None = None,
        top_k: int = 8,
    ) -> list[dict]:
        # Build a set of graph-matched terms for boosting
        graph_terms: set[str] = set()
        if graph_results:
            for gr in graph_results:
                graph_terms.add(gr.get("entity", "").lower())
                graph_terms.add(gr.get("target", "").lower())

        scored = []
        for r in results:
            score = r.get("score", 0.0)
            meta = r.get("metadata", {})
            text = r.get("text", "")

            # Boost for frequency match
            if query_info.frequency_range and self._freq_in_meta(
                query_info.frequency_range, meta
            ):
                score += 0.30

            # Boost for region match
            if query_info.region and self._region_in_meta(query_info.region, meta):
                score += 0.20

            # Boost for service match
            if query_info.radio_service and self._service_in_meta(
                query_info.radio_service, meta
            ):
                score += 0.20

            # Boost for graph entity match
            if graph_terms:
                text_lower = text.lower()
                for term in graph_terms:
                    if term and term in text_lower:
                        score += 0.15
                        break

            # Boost for exact standard/footnote match
            if query_info.standard and self._text_contains(query_info.standard, meta, text):
                score += 0.15
            if query_info.footnote and self._text_contains(query_info.footnote, meta, text):
                score += 0.15

            # Block type priority
            bt = meta.get("block_type", "")
            if bt in ("footnote",):
                score += 0.15
            elif bt in ("table",):
                score += 0.10

            # Source authority
            source = meta.get("source_path", "")
            if "R-REC" in source or "Rec." in source:
                score += 0.05

            scored.append({**r, "rerank_score": round(min(score, 1.0), 4)})

        scored.sort(key=lambda r: r["rerank_score"], reverse=True)
        return scored[:top_k]

    @staticmethod
    def _freq_in_meta(freq: str, meta: dict) -> bool:
        freq_clean = freq.replace(" ", "").lower()
        text = str(meta.get("text", "")) + str(meta.get("freq_ranges", ""))
        return freq_clean in text.replace(" ", "").lower()

    @staticmethod
    def _region_in_meta(region: str, meta: dict) -> bool:
        text = str(meta.get("text", "")) + str(meta.get("regions", ""))
        return region.lower() in text.lower()

    @staticmethod
    def _service_in_meta(service: str, meta: dict) -> bool:
        text = str(meta.get("text", ""))
        return service.lower() in text.lower()

    @staticmethod
    def _text_contains(term: str, meta: dict, text: str) -> bool:
        haystack = (text + " " + str(meta.get("text", ""))).lower()
        return term.lower() in haystack
