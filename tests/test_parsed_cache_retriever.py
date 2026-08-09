from __future__ import annotations

import asyncio
import json


def _write_blocks(root, doc_id, blocks):
    doc_dir = root / doc_id
    doc_dir.mkdir(parents=True)
    (doc_dir / "content_list.json").write_text(json.dumps(blocks), encoding="utf-8")


def test_parsed_cache_retriever_finds_frequency_and_service_evidence(tmp_path):
    _write_blocks(tmp_path, "relevant", [{
        "block_id": "relevant-1",
        "doc_id": "relevant",
        "source_path": "/kb/R-REC-M.TEST.pdf",
        "page_idx": 7,
        "block_type": "table",
        "content": "In Region 3 the band 2 300-2 400 MHz is allocated to the MOBILE service. Coordination and interference protection are required.",
    }])
    _write_blocks(tmp_path, "irrelevant", [{
        "block_id": "irrelevant-1",
        "doc_id": "irrelevant",
        "source_path": "/kb/R-REC-BO.TEST.pdf",
        "page_idx": 2,
        "block_type": "text",
        "content": "Broadcasting satellite antenna reference patterns at 12 GHz.",
    }])

    from backend.rag.retrievers.parsed_cache_retriever import ParsedCacheRetriever

    results = ParsedCacheRetriever(parsed_dir=tmp_path).retrieve(
        "2300-2400 MHz Region 3 Land Mobile 频率划分 干扰保护",
        top_k=5,
    )

    assert results
    assert results[0]["block_id"] == "relevant-1"
    assert results[0]["metadata"]["source_path"].endswith("R-REC-M.TEST.pdf")
    assert results[0]["metadata"]["page_idx"] == 7
    assert results[0]["score"] >= 0.6


def test_frequency_stream_uses_parsed_cache_when_primary_retrievers_are_unavailable(monkeypatch):
    import backend.llm.client as llm_client
    import backend.rag.graph.stream as stream_module

    class ParsedFallback:
        def retrieve(self, query, top_k=12):
            return [{
                "block_id": "fallback-1",
                "text": "2300-2400 MHz is allocated to the mobile service in Region 3.",
                "metadata": {
                    "source_path": "/kb/R-REC-M.TEST.pdf",
                    "page_idx": 7,
                    "block_type": "table",
                    "text": "2300-2400 MHz mobile service Region 3",
                },
                "score": 0.82,
            }]

    def unavailable_vector():
        raise ModuleNotFoundError("chromadb")

    async def fake_stream_chat(messages, **kwargs):
        assert "R-REC-M.TEST.pdf" in messages[-1]["content"]
        yield {"type": "content", "data": "**结论：** 有证据。"}
        yield {"type": "done", "data": {}}

    monkeypatch.setattr(stream_module, "_get_vector_retriever", unavailable_vector)
    monkeypatch.setattr(stream_module, "_get_keyword_retriever", lambda: None)
    monkeypatch.setattr(stream_module, "_get_graph_retriever", lambda: None)
    monkeypatch.setattr(stream_module, "_get_parsed_cache_retriever", lambda: ParsedFallback())
    monkeypatch.setattr(llm_client, "stream_chat", fake_stream_chat)

    events = asyncio.run(_collect(stream_module.stream_rag_query(
        "2300-2400 MHz Region 3 Mobile",
        profile="frequency_plan",
    )))

    done = events[-1]
    assert done["type"] == "done"
    assert done["citations"]
    assert done["citations"][0]["source"].endswith("R-REC-M.TEST.pdf")
    retrieval_done = next(event for event in events if event.get("type") == "stage_done" and event.get("stage") == "retrieval")
    assert retrieval_done["counts"]["parsed_cache"] == 1


def test_frequency_stream_exposes_llm_generation_failure(monkeypatch):
    import backend.llm.client as llm_client
    import backend.rag.graph.stream as stream_module

    class ParsedFallback:
        def retrieve(self, query, top_k=12):
            return [{
                "block_id": "fallback-1",
                "text": "2300-2400 MHz mobile allocation evidence.",
                "metadata": {"source_path": "/kb/R-REC-M.TEST.pdf", "page_idx": 7, "block_type": "text"},
                "score": 0.82,
            }]

    def unavailable_vector():
        raise ModuleNotFoundError("chromadb")

    async def failing_stream_chat(messages, **kwargs):
        raise RuntimeError("model transport failed")
        yield {}

    monkeypatch.setattr(stream_module, "_get_vector_retriever", unavailable_vector)
    monkeypatch.setattr(stream_module, "_get_keyword_retriever", lambda: None)
    monkeypatch.setattr(stream_module, "_get_graph_retriever", lambda: None)
    monkeypatch.setattr(stream_module, "_get_parsed_cache_retriever", lambda: ParsedFallback())
    monkeypatch.setattr(llm_client, "stream_chat", failing_stream_chat)

    events = asyncio.run(_collect(stream_module.stream_rag_query(
        "2300-2400 MHz Mobile",
        profile="frequency_plan",
    )))

    done = events[-1]
    assert done["type"] == "done"
    assert done["generation_status"] == "failed"
    assert done["generation_error"] == "model transport failed"


async def _collect(stream):
    return [event async for event in stream]
