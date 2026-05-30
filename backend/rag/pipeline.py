"""Full document processing pipeline — aligned with RAG-Anything ProcessorMixin.

Complete end-to-end pipeline matching RAG-Anything's process_document_complete():
  1. Parse document → content_list
  2. Separate content → text + multimodal items
  3. Set context source for multimodal processors
  4. Insert text content to vector store (Chroma)
  5. Process multimodal items concurrently with type-aware batching
  6. Extract entities via LLM from processor output
  7. Merge entities/relations into knowledge graph
  8. Update graph JSON on disk

Adapted from RAG-Anything's:
  - raganything/processor.py  (ProcessorMixin)
  - raganything/modalprocessors.py  (BaseModalProcessor, type-aware batch)
  - raganything/utils.py  (separate_content, insert_text_content)
"""

from __future__ import annotations

import json
import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .schemas.block import SpectrumContentBlock
from .schemas.document import SpectrumDocument
from .schemas.graph import SpectrumEntity, SpectrumRelation
from .processor import separate_content, build_multimodal_entity_graph


# ── Constants matching RAG-Anything ──
DEFAULT_MAX_CONCURRENT = 3
from .paths import GRAPH_PATH


@dataclass
class PipelineResult:
    """Result of processing a single document through the pipeline."""
    doc_id: str = ""
    text_blocks: int = 0
    multimodal_items: int = 0
    entities_added: int = 0
    relations_added: int = 0
    errors: list[str] = field(default_factory=list)


class DocumentProcessor:
    """Full RAG-Anything-aligned document processing pipeline.

    Handles one document at a time through the complete parse→process→extract cycle.
    """

    def __init__(
        self,
        parser=None,
        text_proc=None,
        table_proc=None,
        image_proc=None,
        equation_proc=None,
        footnote_proc=None,
        context_builder=None,
        vector_store=None,
        llm_chat_func: Callable | None = None,
        max_concurrent: int = DEFAULT_MAX_CONCURRENT,
        graph_path: Path | None = None,
    ):
        self.parser = parser
        self.text_proc = text_proc
        self.table_proc = table_proc
        self.image_proc = image_proc
        self.equation_proc = equation_proc
        self.footnote_proc = footnote_proc
        self.context_builder = context_builder
        self.vector_store = vector_store
        self.llm_chat = llm_chat_func
        self.max_concurrent = max_concurrent
        self.graph_path = graph_path or GRAPH_PATH

        # Content source for context extraction (set per document)
        self._content_source: list[SpectrumContentBlock] = []

    def set_content_source_for_context(self, blocks: list[SpectrumContentBlock]):
        """Set content source for context extraction — called once per document.

        Matches RAG-Anything's ProcessorMixin.set_content_source_for_context().
        """
        self._content_source = list(blocks)

    async def process_document(self, file_path: str) -> PipelineResult:
        """Main entry point — matches RAG-Anything's process_document_complete().

        Returns PipelineResult with processing statistics.
        """
        result = PipelineResult()
        path = Path(file_path)

        # ── Stage 0: Parse ──
        if self.parser is None:
            result.errors.append("No parser configured")
            return result

        try:
            doc = self.parser.parse(str(path))
            result.doc_id = doc.doc_id
        except Exception as exc:
            result.errors.append(f"Parse failed: {exc}")
            return result

        if not doc.blocks:
            result.errors.append("No blocks extracted from document")
            return result

        # ── Stage 1: Separate content (matching RAG-Anything) ──
        text_blocks, multimodal_items = separate_content(doc.blocks)
        result.text_blocks = len(text_blocks)
        result.multimodal_items = len(multimodal_items)

        # ── Stage 2: Set content source for context ──
        self.set_content_source_for_context(doc.blocks)

        # ── Stage 3: Process text blocks (context-aware) ──
        for i, block in enumerate(text_blocks):
            ctx = None
            if self.context_builder:
                ctx = self.context_builder.build_from_blocks(doc.blocks, i)

            proc = self.footnote_proc if block.block_type == "footnote" else self.text_proc
            if proc:
                proc.process(block, ctx)
                block.processing_status = "enhanced"

        # ── Stage 4: Insert ALL enhanced blocks to vector store ──
        # Text blocks go directly. Multimodal blocks get enhanced_content from processors.
        all_enhanced = list(text_blocks)
        if self.vector_store and all_enhanced:
            try:
                self.vector_store.add_blocks(all_enhanced)
            except Exception as exc:
                result.errors.append(f"Vector store text insert failed: {exc}")

        # ── Stage 5: Process multimodal items (type-aware, concurrent) ──
        all_entities: list[SpectrumEntity] = []
        all_relations: list[SpectrumRelation] = []

        if multimodal_items:
            sem = asyncio.Semaphore(self.max_concurrent)

            async def _process_item(item: SpectrumContentBlock):
                ctx = None
                idx = next((j for j, b in enumerate(doc.blocks) if b.block_id == item.block_id), -1)
                if self.context_builder and idx >= 0:
                    ctx = self.context_builder.build_from_blocks(doc.blocks, idx)

                proc_map = {
                    "table": self.table_proc,
                    "image": self.image_proc,
                    "chart": self.image_proc,
                    "equation": self.equation_proc,
                    "footnote": self.footnote_proc,
                }
                proc = proc_map.get(item.block_type)

                async with sem:
                    try:
                        if proc:
                            if hasattr(proc, 'process_async'):
                                await proc.process_async(item, ctx)
                            else:
                                proc.process(item, ctx)

                        ents, rels = await build_multimodal_entity_graph(
                            {}, item, doc.doc_id, doc.source_path or str(path),
                            self.llm_chat,
                        )
                        return ents, rels
                    except Exception:
                        return [], []

            tasks = [_process_item(item) for item in multimodal_items]
            batch_results = await asyncio.gather(*tasks)
            for ents, rels in batch_results:
                all_entities.extend(ents)
                all_relations.extend(rels)

        result.entities_added = len(all_entities)
        result.relations_added = len(all_relations)

        # ── Stage 5b: Insert multimodal enhanced blocks to vector store ──
        for item in multimodal_items:
            if item.enhanced_content and self.vector_store:
                try:
                    self.vector_store.add_blocks([item])
                except Exception:
                    pass

        # ── Stage 6: Merge entities/relations into graph JSON ──
        if all_entities or all_relations:
            try:
                _merge_into_graph_json(self.graph_path, all_entities, all_relations)
            except Exception as exc:
                result.errors.append(f"Graph merge failed: {exc}")

        return result


def _merge_into_graph_json(
    path: Path,
    new_entities: list[SpectrumEntity],
    new_relations: list[SpectrumRelation],
):
    """Merge new entities/relations into the persistent graph JSON file.

    Matches RAG-Anything's merge_nodes_and_edges() pattern:
    deduplicates by (name, type) for entities, and by (source, relation, target)
    for relations.

    Also adds DocumentStructureGraph entries for the document itself.
    """
    existing = {"entities": [], "relations": []}
    if path.exists():
        try:
            existing = json.loads(path.read_text())
        except Exception:
            pass

    # Dedup entities by (name, type)
    entity_map: dict[tuple, dict] = {}
    for e in existing.get("entities", []):
        key = (e.get("name", ""), e.get("type", ""))
        entity_map[key] = e
    for e in new_entities:
        key = (e.name, e.type)
        if key not in entity_map:
            entity_map[key] = e.to_dict()

    # Dedup relations by (source, relation, target)
    rel_set: set[tuple] = set()
    for r in existing.get("relations", []):
        key = (r.get("source", ""), r.get("relation", ""), r.get("target", ""))
        rel_set.add(key)
    new_rel_dicts = []
    for r in new_relations:
        key = (r.source, r.relation, r.target)
        if key not in rel_set:
            rel_set.add(key)
            new_rel_dicts.append(r.to_dict())

    graph = {
        "entities": list(entity_map.values()),
        "relations": existing.get("relations", []) + new_rel_dicts,
        "entity_count": len(entity_map),
        "relation_count": len(existing.get("relations", [])) + len(new_rel_dicts),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(graph, ensure_ascii=False, indent=2))
