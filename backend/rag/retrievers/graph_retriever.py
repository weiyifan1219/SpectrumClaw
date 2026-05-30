"""Graph retriever — traverse the spectrum knowledge graph for related entities."""

from __future__ import annotations

import json
from pathlib import Path

from ..paths import GRAPH_PATH


class GraphRetriever:
    """Retrieve related entities and evidence from the spectrum knowledge graph.

    Given query entities (frequency bands, services, regions), traverse
    the graph to find related concepts and their evidence blocks.
    """

    def __init__(self, graph_path: Path | None = None):
        self._graph_path = graph_path or GRAPH_PATH
        self._entities: dict[str, dict] = {}
        self._relations: list[dict] = []
        self._loaded = False

    def is_available(self) -> bool:
        return self._graph_path.exists()

    def retrieve(self, query_entities: dict) -> list[dict]:
        """Find graph paths related to query entities.

        query_entities: dict with keys like frequency_range, region, radio_service, etc.
        Returns list of {entity, relation, target, evidence_block_id}.
        """
        if not self.is_available():
            return []
        self._ensure_loaded()

        results = []
        search_terms = self._extract_search_terms(query_entities)

        # Find matching entities and their relations
        matched_entities = []
        for name, info in self._entities.items():
            for term in search_terms:
                if term.lower() in name.lower():
                    matched_entities.append(name)
                    break

        # Get relations for matched entities
        for rel in self._relations:
            if rel["source"] in matched_entities or rel["target"] in matched_entities:
                results.append({
                    "entity": rel["source"],
                    "relation": rel["relation"],
                    "target": rel["target"],
                    "evidence_block_id": rel.get("evidence_block_id", ""),
                    "confidence": rel.get("confidence", 1.0),
                })

        return results[:20]

    def _extract_search_terms(self, query_entities: dict) -> list[str]:
        terms = []
        for key in ("frequency_range", "region", "radio_service", "standard", "footnote"):
            val = query_entities.get(key)
            if val:
                terms.append(str(val))
        return terms

    def _ensure_loaded(self):
        if self._loaded:
            return
        data = json.loads(self._graph_path.read_text())
        for e in data.get("entities", []):
            self._entities[e["name"]] = e
        self._relations = data.get("relations", [])
        self._loaded = True

    @property
    def entity_count(self) -> int:
        self._ensure_loaded()
        return len(self._entities)

    @property
    def relation_count(self) -> int:
        self._ensure_loaded()
        return len(self._relations)
