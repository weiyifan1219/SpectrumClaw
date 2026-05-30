"""RAG-Anything aligned processing pipeline: separate → process → extract entities.

Mirrors raganything/processor.py ProcessorMixin pattern, adapted to:
- LangChain + LangGraph (our stack) instead of LightRAG
- ChromaDB + sentence-transformers for storage
- llm.client.chat() for LLM entity extraction
"""

from __future__ import annotations

import json
import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .schemas.block import SpectrumContentBlock
from .schemas.graph import SpectrumEntity, SpectrumRelation


# ── 1. Content Separation (aligned with raganything/utils.py separate_content) ──

def separate_content(
    blocks: list[SpectrumContentBlock],
) -> tuple[list[SpectrumContentBlock], list[SpectrumContentBlock]]:
    """Split content_list into text blocks and multimodal items.

    Text blocks (text, title) are for direct embedding.
    Multimodal items (image, table, equation, footnote, chart) need
    specialized processing before embedding.

    Matches RAG-Anything's separate_content() pattern exactly.
    """
    text_blocks: list[SpectrumContentBlock] = []
    multimodal_items: list[SpectrumContentBlock] = []

    for b in blocks:
        if b.block_type in ("text", "title"):
            text_blocks.append(b)
        else:
            multimodal_items.append(b)

    return text_blocks, multimodal_items


# ── 2. LLM Entity Extraction (aligned with LightRAG extract_entities) ──

EXTRACT_ENTITIES_PROMPT = """Extract spectrum-domain entities and relations from the following content.
Output ONLY a JSON object with "entities" and "relations" arrays.

Entity types allowed:
- FrequencyBand: frequency ranges (e.g. "2300-2400 MHz", "5.8 GHz")
- RadioService: radio communication services (e.g. "Mobile Service", "Fixed-Satellite")
- Region: ITU Region 1/2/3
- Footnote: ITU-R footnote numbers (e.g. "5.340", "5.432A")
- Standard: ITU-R Recommendation numbers (e.g. "ITU-R M.1457")
- DeviceType: equipment types (e.g. "Base Station", "Earth Station")
- Constraint: restriction or condition (e.g. "power limit 20 dBm", "no emission")
- Variable: equation variable (e.g. "EIRP", "C/N ratio", "path loss")
- Organization: standards bodies (e.g. "ITU", "CEPT", "FCC")

Relation types allowed:
- allocated_to: FrequencyBand → RadioService
- limited_by: FrequencyBand → Footnote/Constraint
- applies_in: FrequencyBand → Region
- defined_by: Standard → Organization
- mentioned_in: any → Document
- belongs_to: any entity → block_id (use the context_block_id below)

Rules:
- Only extract entities that are EXPLICITLY mentioned in the content
- Never fabricate frequency values, footnote numbers, or standard references
- Each entity must have a name and type
- Each relation must have source, relation, and target
- If unsure, skip — do not guess

Context block ID for belongs_to relations: {context_block_id}

Content to analyze:
{content}"""


async def extract_entities_from_content(
    content: str,
    context_block_id: str = "",
    llm_chat_func=None,
) -> tuple[list[dict], list[dict]]:
    """Use LLM to extract entities and relations from processor output.

    Aligned with LightRAG's extract_entities() pattern: takes enhanced text,
    returns structured entities and relations.
    """
    if not llm_chat_func:
        return [], []

    prompt = EXTRACT_ENTITIES_PROMPT.format(
        context_block_id=context_block_id,
        content=content[:6000],
    )
    msgs = [
        {"role": "system", "content": "You are a spectrum knowledge graph builder. "
         "Extract structured entities and relations from technical documents. "
         "Output valid JSON only. No markdown, no explanation."},
        {"role": "user", "content": prompt},
    ]

    try:
        reply = await llm_chat_func(msgs)
        # Parse JSON from reply (handle markdown code blocks)
        json_str = reply.strip()
        if "```json" in json_str:
            json_str = json_str.split("```json")[1].split("```")[0]
        elif "```" in json_str:
            json_str = json_str.split("```")[1].split("```")[0]
        data = json.loads(json_str)
        entities = data.get("entities", [])
        relations = data.get("relations", [])
        return entities, relations
    except Exception:
        return [], []


# ── 3. Belongs To Relations ──

async def build_multimodal_entity_graph(
    processor_output: dict,
    block: SpectrumContentBlock,
    doc_id: str,
    source_path: str,
    llm_chat_func=None,
) -> tuple[list[SpectrumEntity], list[SpectrumRelation]]:
    """Build entity/relation graph from a multimodal processor's output.

    This mirrors RAG-Anything's Stage 4-6 of _process_multimodal_content_batch_type_aware():
    1. Extract entities from the processor's enhanced_content via LLM
    2. Create an entity for the multimodal item itself (image/table/equation)
    3. Add belongs_to relations linking extracted entities to the item entity

    Returns (entities_to_add, relations_to_add).
    """
    entities_out: list[SpectrumEntity] = []
    relations_out: list[SpectrumRelation] = []

    # ── Create multimodal entity for the item itself ──
    item_name = f"{block.block_type}:{block.block_id}"
    if block.caption:
        item_name = block.caption[0][:80]
    elif block.content:
        item_name = block.content[:80]

    item_entity = SpectrumEntity(
        name=item_name,
        type=block.block_type.capitalize(),
        evidence_block_id=block.block_id,
        confidence=1.0,
        extractor="processor",
        metadata={"doc_id": doc_id, "source_path": source_path,
                  "block_id": block.block_id, "page_idx": block.page_idx},
    )
    entities_out.append(item_entity)

    # ── Add belongs_to: this item → document ──
    doc_entity_name = f"Document:{doc_id}"
    relations_out.append(SpectrumRelation(
        source=item_name,
        relation="belongs_to",
        target=doc_entity_name,
        evidence_block_id=block.block_id,
        confidence=1.0,
        extractor="processor",
        doc_id=doc_id,
        page_idx=block.page_idx,
        source_path=source_path,
    ))

    # ── LLM entity extraction from enhanced_content ──
    enhanced = block.enhanced_content or block.content
    if enhanced and llm_chat_func:
        llm_entities, llm_relations = await extract_entities_from_content(
            enhanced, context_block_id=block.block_id, llm_chat_func=llm_chat_func,
        )
        for e in llm_entities:
            ee = SpectrumEntity(
                name=e.get("name", ""),
                type=e.get("type", "Unknown"),
                evidence_block_id=block.block_id,
                confidence=e.get("confidence", 0.8),
                extractor="llm",
                metadata={"doc_id": doc_id, "source_path": source_path, "block_id": block.block_id},
            )
            entities_out.append(ee)
            # belongs_to: extracted entity → multimodal item
            relations_out.append(SpectrumRelation(
                source=ee.name,
                relation="belongs_to",
                target=item_name,
                evidence_block_id=block.block_id,
                confidence=0.8,
                extractor="llm",
                doc_id=doc_id,
                page_idx=block.page_idx,
                source_path=source_path,
            ))
        for r in llm_relations:
            relations_out.append(SpectrumRelation(
                source=r.get("source", ""),
                relation=r.get("relation", "mentioned_in"),
                target=r.get("target", ""),
                evidence_block_id=block.block_id,
                confidence=0.8,
                extractor="llm",
                doc_id=doc_id,
                page_idx=block.page_idx,
                source_path=source_path,
            ))

    return entities_out, relations_out


# ── 4. Full Multimodal Processing Pipeline ──

@dataclass
class MultimodalProcessResult:
    text_blocks: list[SpectrumContentBlock] = field(default_factory=list)
    multimodal_entities: list[SpectrumEntity] = field(default_factory=list)
    multimodal_relations: list[SpectrumRelation] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


async def process_multimodal_content(
    text_blocks: list[SpectrumContentBlock],
    multimodal_items: list[SpectrumContentBlock],
    doc_id: str,
    source_path: str,
    llm_chat_func=None,
    image_processor=None,
    table_processor=None,
    equation_processor=None,
    context_builder=None,
    max_concurrent: int = 3,
) -> MultimodalProcessResult:
    """Process multimodal items with LLM entity extraction.

    Aligned with RAG-Anything's _process_multimodal_content_batch_type_aware():
    - Stage 1: Process each item with its modality processor (concurrent)
    - Stage 2: Extract entities via LLM for each processed item
    - Stage 3: Build belongs_to relations linking everything together
    """
    all_entities: list[SpectrumEntity] = []
    all_relations: list[SpectrumRelation] = []

    sem = asyncio.Semaphore(max_concurrent)

    async def _process_one(item: SpectrumContentBlock):
        """Process a single multimodal block and extract its entity graph."""
        proc_map = {
            "table": table_processor,
            "image": image_processor,
            "chart": image_processor,
            "equation": equation_processor,
        }
        proc = proc_map.get(item.block_type)
        if proc and context_builder:
            ctx = context_builder.build_from_blocks(
                text_blocks + multimodal_items,
                next(i for i, b in enumerate(text_blocks + multimodal_items)
                     if b.block_id == item.block_id),
            )
        else:
            ctx = None

        async with sem:
            try:
                # Process through modality processor (use async if available)
                if hasattr(proc, 'process_async'):
                    await proc.process_async(item, ctx)
                elif proc:
                    proc.process(item, ctx)

                # Build entity graph from processor output
                ents, rels = await build_multimodal_entity_graph(
                    {}, item, doc_id, source_path, llm_chat_func,
                )
                return ents, rels
            except Exception:
                return [], []

    # Process all multimodal items concurrently
    tasks = [_process_one(item) for item in multimodal_items]
    results = await asyncio.gather(*tasks)

    for ents, rels in results:
        all_entities.extend(ents)
        all_relations.extend(rels)

    return MultimodalProcessResult(
        text_blocks=text_blocks,
        multimodal_entities=all_entities,
        multimodal_relations=all_relations,
        stats={
            "text_blocks": len(text_blocks),
            "multimodal_items": len(multimodal_items),
            "extracted_entities": len(all_entities),
            "extracted_relations": len(all_relations),
        },
    )
