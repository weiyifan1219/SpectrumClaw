"""RAG evaluation runner — test retrieval + answer quality on a question set."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
QUESTIONS_PATH = PROJECT_ROOT / "data" / "eval" / "spectrum_rag_questions.json"
REPORTS_DIR = PROJECT_ROOT / "data" / "eval" / "reports"


async def run_eval() -> dict:
    """Run evaluation on all test questions. Returns summary dict."""
    if not QUESTIONS_PATH.exists():
        return {"error": f"Questions file not found: {QUESTIONS_PATH}"}

    questions = json.loads(QUESTIONS_PATH.read_text())
    results = []

    from ..retrievers.query_analyzer import SpectrumQueryAnalyzer
    from ..retrievers.vector_retriever import VectorRetriever
    from ..embeddings.sentence_transformer import SentenceTransformersEmbeddingProvider
    from ..vectorstores.chroma_store import ChromaStore

    chroma_dir = PROJECT_ROOT / "data" / "chroma"
    analyzer = SpectrumQueryAnalyzer()

    if chroma_dir.exists():
        emb = SentenceTransformersEmbeddingProvider()
        store = ChromaStore(persist_dir=chroma_dir, embedding_provider=emb)
        vector_retriever = VectorRetriever(store)
    else:
        vector_retriever = None

    for q in questions:
        qi = analyzer.analyze(q["question"])
        qi_dict = qi.to_dict()

        # Check entity extraction
        expected_entities = q.get("expected_entities", [])
        extracted_all = " ".join(
            v for v in [
                qi_dict.get("frequency_range"),
                qi_dict.get("region"),
                qi_dict.get("radio_service"),
                qi_dict.get("standard"),
                qi_dict.get("footnote"),
            ] if v
        )
        entity_hits = sum(1 for e in expected_entities if e.lower() in extracted_all.lower())
        entity_score = entity_hits / len(expected_entities) if expected_entities else 1.0

        # Check retrieval
        retrieval_hits = 0
        retrieval_count = 0
        if vector_retriever:
            vec_results = vector_retriever.retrieve(q["question"])
            retrieval_count = len(vec_results)
            for r in vec_results:
                source = r.get("metadata", {}).get("source_path", "")
                if q.get("expected_doc_pattern", "").lower() in source.lower():
                    retrieval_hits += 1

        results.append({
            "question_id": q["id"],
            "question": q["question"],
            "query_info": qi_dict,
            "entity_hits": entity_hits,
            "entity_total": len(expected_entities),
            "entity_score": round(entity_score, 3),
            "retrieval_count": retrieval_count,
            "retrieval_hits": retrieval_hits,
        })

    summary = {
        "total_questions": len(questions),
        "avg_entity_score": round(
            sum(r["entity_score"] for r in results) / len(results), 3
        ) if results else 0,
        "avg_retrieval_count": round(
            sum(r["retrieval_count"] for r in results) / len(results), 1
        ) if results else 0,
        "total_retrieval_hits": sum(r["retrieval_hits"] for r in results),
        "results": results,
    }

    # Save report
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_path = REPORTS_DIR / f"{date_str}.json"
    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2))

    return summary


if __name__ == "__main__":
    import asyncio
    report = asyncio.run(run_eval())
    print(json.dumps({k: v for k, v in report.items() if k != "results"}, ensure_ascii=False, indent=2))
