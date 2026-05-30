"""Metadata filter builder — converts QueryInfo to Chroma-compatible where clauses."""

from __future__ import annotations


def build_metadata_filter(
    doc_id: str | None = None,
    block_type: str | None = None,
    region: str | None = None,
    source_path_contains: str | None = None,
) -> dict | None:
    """Build a Chroma-compatible metadata filter dict.

    Chroma supports $and/$or with $eq/$ne/$contains operators on metadata fields.
    """
    conditions = []

    if doc_id:
        conditions.append({"doc_id": {"$eq": doc_id}})
    if block_type:
        conditions.append({"block_type": {"$eq": block_type}})
    if source_path_contains:
        conditions.append({"source_path": {"$contains": source_path_contains}})

    if not conditions:
        return None
    if len(conditions) == 1:
        return conditions[0]
    return {"$and": conditions}
