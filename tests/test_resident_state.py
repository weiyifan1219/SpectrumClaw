from __future__ import annotations

import json
import os
import sqlite3


def test_resident_state_refreshes_registry_graph_and_vectors(tmp_path, monkeypatch):
    import backend.runtime.resident_state as resident

    doc_registry = tmp_path / "doc_registry.json"
    graph_path = tmp_path / "graph.json"
    tfidf_meta = tmp_path / "meta.json"
    tfidf_db = tmp_path / "kb.sqlite3"
    chroma_dir = tmp_path / "chroma"
    chroma_dir.mkdir()
    chroma_db = chroma_dir / "chroma.sqlite3"
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    local_vlm_dir = tmp_path / "MinerU2.5-Pro-2605-1.2B"
    local_vlm_dir.mkdir()

    with sqlite3.connect(str(chroma_db)) as db:
        db.execute("CREATE TABLE embeddings (id INTEGER PRIMARY KEY)")
        db.executemany("INSERT INTO embeddings DEFAULT VALUES", [(), (), ()])
        db.commit()

    tfidf_meta.write_text(json.dumps({"status": "ready", "total_chunks": 5, "total_chars": 42}))
    doc_registry.write_text(json.dumps({
        "docs": {
            "doc_a": {"content_hash": "doc_a", "filename": "A.pdf", "status": "indexed"},
        }
    }))
    graph_path.write_text(json.dumps({
        "entities": [{"name": "2300-2400 MHz", "type": "FrequencyBand"}],
        "relations": [{"source": "2300-2400 MHz", "relation": "allocated_to", "target": "Mobile Service"}],
        "entity_count": 1,
        "relation_count": 1,
    }))

    monkeypatch.setattr(resident, "DOC_REGISTRY_PATH", doc_registry)
    monkeypatch.setattr(resident, "GRAPH_PATH", graph_path)
    monkeypatch.setattr(resident, "TFIDF_META_PATH", tfidf_meta)
    monkeypatch.setattr(resident, "TFIDF_DB_PATH", tfidf_db)
    monkeypatch.setattr(resident, "CHROMA_DIR", chroma_dir)
    monkeypatch.setattr(resident, "CHROMA_DB_PATH", chroma_db)
    monkeypatch.setattr(resident, "KB_RAW_DIR", raw_dir)
    monkeypatch.setenv("QWEN_VL_MODE", "local")
    monkeypatch.setenv("QWEN_VL_LOCAL_MODEL_PATH", str(local_vlm_dir))

    state = resident.ResidentRuntimeState()
    first = state.kb_stats()

    assert first["total_pdfs"] == 1
    assert first["knowledge_graph"]["entity_count"] == 1
    assert first["rag_pipeline"]["vector_count"] == 3
    assert first["resident"]["vlm"]["mode"] == "local"
    assert first["resident"]["vlm"]["model"] == "MinerU2.5-Pro-2605-1.2B"

    doc_registry.write_text(json.dumps({
        "docs": {
            "doc_a": {"content_hash": "doc_a", "filename": "A.pdf", "status": "indexed"},
            "doc_b": {"content_hash": "doc_b", "filename": "B.pdf", "status": "indexed"},
        }
    }))
    graph_path.write_text(json.dumps({
        "entities": [
            {"name": "2300-2400 MHz", "type": "FrequencyBand"},
            {"name": "EIRP", "type": "Variable"},
        ],
        "relations": [{"source": "EIRP", "relation": "belongs_to", "target": "eq:block_1"}],
        "entity_count": 2,
        "relation_count": 1,
    }))
    os.utime(doc_registry, None)
    os.utime(graph_path, None)
    state.mark_rag_dirty()

    second = state.kb_stats()
    entity_payload = state.graph_entity("EIRP")

    assert second["total_pdfs"] == 2
    assert second["knowledge_graph"]["entity_count"] == 2
    assert entity_payload["entity"]["type"] == "Variable"
    assert entity_payload["relations"][0]["relation"] == "belongs_to"
