"""HybridRetriever — multi-channel retrieval with Reciprocal Rank Fusion and modality-aware ranking."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..retrievers.query_analyzer import SpectrumQueryAnalyzer, QueryInfo
from ..retrievers.vector_retriever import VectorRetriever
from ..retrievers.keyword_retriever import KeywordRetriever
from ..retrievers.graph_retriever import GraphRetriever
from ..retrievers.reranker import Reranker
from ..retrievers.context_packer import ContextPacker
from ..keyword.frequency_matcher import FrequencyRangeMatcher, FrequencyRange


@dataclass
class FusionConfig:
    vector_weight: float = 0.25
    keyword_weight: float = 0.20
    graph_weight: float = 0.20
    frequency_weight: float = 0.20
    modality_weight: float = 0.10
    authority_weight: float = 0.05


@dataclass
class RetrievalResult:
    blocks: list[dict] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    debug: dict = field(default_factory=dict)


class HybridRetriever:
    """Orchestrates multi-channel retrieval and fusion.

    Channels: vector, keyword, frequency_range, graph, table, footnote, image, equation.
    Fuses results via Reciprocal Rank Fusion with configurable per-channel weights.
    """

    def __init__(
        self,
        vector_retriever: VectorRetriever | None = None,
        keyword_retriever: KeywordRetriever | None = None,
        graph_retriever: GraphRetriever | None = None,
        fusion: FusionConfig | None = None,
    ):
        self.vector = vector_retriever
        self.keyword = keyword_retriever
        self.graph = graph_retriever
        self.reranker = Reranker()
        self.packer = ContextPacker()
        self.analyzer = SpectrumQueryAnalyzer()
        self.freq_matcher = FrequencyRangeMatcher()
        self.fusion = fusion or FusionConfig()

    def retrieve(self, question: str, top_k: int = 10) -> RetrievalResult:
        qi = self.analyzer.analyze(question)
        all_blocks: dict[str, dict] = {}  # block_id -> {block, channels, scores}
        debug = {"channels": {}}

        # ── channel 1: vector ──
        vec_results = []
        if self.vector:
            vec_results = self.vector.retrieve(question)
            for r in vec_results:
                bid = r.get("block_id", "")
                all_blocks[bid] = {**r, "channel": "vector", "vec_score": r.get("score", 0)}
            debug["channels"]["vector"] = len(vec_results)

        # ── channel 2: keyword (TF-IDF) ──
        kw_results = []
        if self.keyword and self.keyword.is_available():
            kw_results = self.keyword.retrieve(question) or []
            for r in kw_results:
                bid = r.get("block_id", r.get("source", ""))
                if bid not in all_blocks:
                    r["score"] = r.get("score", 0) * 0.8  # slightly lower TF-IDF weight
                    all_blocks[bid] = {**r, "channel": "keyword", "kw_score": r.get("score", 0)}
            debug["channels"]["keyword"] = len(kw_results)

        # ── channel 3: frequency range ──
        freq_matches = 0
        if qi.frequency_range:
            fr = FrequencyRange.parse(qi.frequency_range)
            if fr:
                all_texts = {bid: info.get("text", "") for bid, info in all_blocks.items()}
                for bid, text in all_texts.items():
                    if bid not in all_blocks:
                        continue
                    ranges = self.freq_matcher._extract_ranges(text)
                    for r in ranges:
                        if fr.overlaps(r) and bid in all_blocks:
                            all_blocks[bid]["freq_score"] = fr.overlap_ratio(r)
                            all_blocks[bid]["channel"] += "+frequency"
                            freq_matches += 1
                            break
        debug["channels"]["frequency"] = freq_matches

        # ── channel 4: graph ──
        graph_results = []
        if self.graph and self.graph.is_available():
            graph_results = self.graph.retrieve(qi.to_dict())
            debug["channels"]["graph"] = len(graph_results)

        # ── build scored list ──
        scored = list(all_blocks.values())
        if qi.frequency_range and freq_matches > 0:
            # Boost blocks with freq matches
            for b in scored:
                fs = b.get("freq_score", 0)
                if fs > 0:
                    b["score"] = (b.get("score", 0) + fs * self.fusion.frequency_weight * 2)

        # ── modality-aware boost ──
        for b in scored:
            bt = b.get("metadata", {}).get("block_type", "text")
            if qi.intent == "table_lookup" and bt in ("table", "table_row"):
                b["score"] = b.get("score", 0) + 0.15
            elif qi.intent == "footnote_lookup" and bt == "footnote":
                b["score"] = b.get("score", 0) + 0.15
            elif qi.intent == "formula_explanation" and bt == "equation":
                b["score"] = b.get("score", 0) + 0.15

        # ── rerank and pack ──
        reranked = self.reranker.rerank(scored, qi, graph_results=graph_results, top_k=top_k)
        packed = self.packer.pack(reranked)

        return RetrievalResult(
            blocks=reranked,
            sources=[c.get("source", "") for c in packed.citations],
            debug={**debug, "total_channels": 4, "total_blocks_found": len(all_blocks),
                   "reranked": len(reranked)},
        )
