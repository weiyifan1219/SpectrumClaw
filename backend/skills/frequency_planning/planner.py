"""Frequency Planner — RAG-powered spectrum allocation analysis.

Queries the RAG pipeline for ITU-R frequency allocation data and returns
structured planning results with citations.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FrequencyPlanResult:
    query: str
    frequency_band: str = ""
    region: str = ""
    services: list[str] = field(default_factory=list)
    allocation_status: str = ""  # primary / secondary / not allocated
    constraints: list[str] = field(default_factory=list)
    footnotes: list[str] = field(default_factory=list)
    adjacent_bands: list[str] = field(default_factory=list)
    citations: list[dict] = field(default_factory=list)
    answer: str = ""
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "frequency_band": self.frequency_band,
            "region": self.region,
            "services": self.services,
            "allocation_status": self.allocation_status,
            "constraints": self.constraints,
            "footnotes": self.footnotes,
            "adjacent_bands": self.adjacent_bands,
            "citations": self.citations,
            "answer": self.answer,
            "errors": self.errors,
        }


class FrequencyPlanner:
    """Analyze frequency allocation using the RAG pipeline.

    Usage:
        planner = FrequencyPlanner()
        result = await planner.analyze("2300-2400 MHz", region="Region 3")
    """

    async def analyze(self, band: str, region: str = "",
                       service: str = "", country: str = "") -> FrequencyPlanResult:
        """Analyze a frequency band allocation using the RAG pipeline."""
        q_parts = [f"{band} 频段"]
        if region:
            q_parts.append(region)
        if service:
            q_parts.append(f"{service} 业务分配")
        if country:
            q_parts.append(country)
        q_parts.append("频率划分 限制条件 脚注")
        query = " ".join(q_parts)

        result = FrequencyPlanResult(
            query=query,
            frequency_band=band,
            region=region,
        )

        try:
            from ...rag.graph.workflow import run_rag_query
            rag_result = await run_rag_query(query)
            result.answer = rag_result.get("answer", "")
            result.citations = rag_result.get("citations", [])

            # Parse structured info from query analysis
            debug = rag_result.get("debug", {})
            qi = debug.get("query_analysis", {})

            # Extract services from answer
            answer_lower = result.answer.lower()
            svc_keywords = {
                "mobile": "Mobile Service",
                "fixed": "Fixed Service",
                "broadcasting": "Broadcasting Service",
                "satellite": "Satellite Service",
                "aeronautical": "Aeronautical Mobile",
                "maritime": "Maritime Mobile",
                "radiolocation": "Radiolocation",
                "radionavigation": "Radionavigation",
                "amateur": "Amateur Service",
                "radio astronomy": "Radio Astronomy",
                "meteorological": "Meteorological",
                "space research": "Space Research",
                "earth exploration": "Earth Exploration-Satellite",
            }
            result.services = [v for k, v in svc_keywords.items() if k in answer_lower]

            # Extract constraint keywords
            constraint_kw = ["primary", "secondary", "not allocated", "cannot",
                             "restricted", "limited", "prohibited", "protection"]
            result.constraints = [kw for kw in constraint_kw if kw in answer_lower]

            # Extract footnote references
            import re
            footnotes = set(re.findall(r"5\.\d{3}[A-Z]?", result.answer))
            result.footnotes = list(footnotes)

        except Exception as exc:
            result.errors.append(str(exc))

        return result


async def plan_frequency(band: str, **kwargs) -> FrequencyPlanResult:
    """Convenience function: plan a frequency band allocation."""
    planner = FrequencyPlanner()
    return await planner.analyze(band, **kwargs)
