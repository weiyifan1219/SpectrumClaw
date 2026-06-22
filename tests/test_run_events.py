from __future__ import annotations

from backend.agent.run_events import (
    SCHEMA_VERSION,
    content,
    done,
    stage,
    stage_done,
    standardize_event,
)


def test_stage_events_keep_legacy_type_and_add_contract_fields():
    started = stage("router", "Route Request")
    finished = stage_done("router", data={"intent": "rag"})

    assert started["type"] == "stage"
    assert started["event"] == "stage"
    assert started["status"] == "started"
    assert started["schema_version"] == SCHEMA_VERSION

    assert finished["type"] == "stage_done"
    assert finished["event"] == "stage"
    assert finished["status"] == "done"
    assert finished["data"]["intent"] == "rag"


def test_content_done_and_legacy_standardization_are_additive():
    token = content("hello", source="llm")
    finished = done({"model": "deepseek-v4-pro"})
    legacy = standardize_event({"type": "done", "citations": [1], "debug": {"x": 1}}, source="rag")

    assert token["type"] == "content"
    assert token["event"] == "content"
    assert token["source"] == "llm"
    assert finished["status"] == "done"
    assert legacy["type"] == "done"
    assert legacy["data"]["citations"] == [1]
    assert legacy["data"]["debug"] == {"x": 1}
    assert legacy["citations"] == [1]
    assert legacy["debug"] == {"x": 1}
