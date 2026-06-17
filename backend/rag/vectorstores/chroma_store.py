"""Chroma vector store — block-level embedding index with metadata filtering."""

from __future__ import annotations

import re
from pathlib import Path

from ..models import SpectrumContentBlock


def _disable_chroma_posthog_telemetry() -> None:
    """Disable ChromaDB's PostHog client to avoid known posthog API mismatch noise."""
    try:
        import posthog
        posthog.disabled = True
        posthog.capture = lambda *args, **kwargs: None
    except Exception:
        pass


class ChromaStore:
    """ChromaDB-backed vector store for SpectrumContentBlocks.

    Each block's enhanced_content is embedded and stored alongside metadata:
    doc_id, page_idx, block_type, source_path, section_path, freq_ranges, etc.
    """

    def __init__(
        self,
        persist_dir: str | Path | None = None,
        collection_name: str = "spectrum_blocks",
        embedding_provider=None,
    ):
        self._persist_dir = str(persist_dir) if persist_dir else None
        self._collection_name = collection_name
        self._embedding_provider = embedding_provider
        self._client = None
        self._collection = None

    # ── public API ──

    def add_blocks(self, blocks: list[SpectrumContentBlock]):
        """Embed and store blocks in Chroma, skipping junk chunks at ingest time."""
        if not blocks:
            return

        # Filter out junk before embedding (cheaper than filtering at search time)
        clean_blocks = [
            b for b in blocks
            if not self._is_junk_chunk(b.enhanced_content or b.content, min_chars=60)
        ]
        if not clean_blocks:
            return

        col = self._get_collection()
        texts = [b.enhanced_content or b.content for b in clean_blocks]
        embeddings = self._embedding_provider.embed_texts(texts)
        ids = [b.block_id for b in clean_blocks]
        metadatas = [self._block_metadata(b) for b in clean_blocks]

        # Chroma has a batch size limit; insert in chunks of 200
        batch = 200
        for i in range(0, len(ids), batch):
            col.add(
                ids=ids[i:i + batch],
                embeddings=embeddings[i:i + batch],
                metadatas=metadatas[i:i + batch],
                documents=texts[i:i + batch],
            )

    def search(
        self,
        query: str,
        top_k: int = 10,
        where: dict | None = None,
        min_chars: int = 60,
    ) -> list[dict]:
        """Search for top-k blocks matching query. Returns list of {block_id, metadata, score}.

        Over-fetches then drops junk short chunks (page headers/footers like
        "Rec. ITU-R P.372-17") and near-duplicate texts, so substantive body
        content survives into the returned top_k instead of being crowded out
        by the many repeated header chunks in the corpus.
        """
        col = self._get_collection()
        query_embedding = self._embedding_provider.embed_query(query)

        fetch_n = max(top_k * 20, 200)
        results = col.query(
            query_embeddings=[query_embedding],
            n_results=fetch_n,
            where=where,
            include=["metadatas", "documents", "distances"],
        )

        kept: list[dict] = []
        seen_norm: set[str] = set()
        if results["ids"] and results["ids"][0]:
            for i, block_id in enumerate(results["ids"][0]):
                meta = results["metadatas"][0][i] if results["metadatas"] else {}
                doc = results["documents"][0][i] if results["documents"] else ""
                dist = results["distances"][0][i] if results["distances"] else 0

                if self._is_junk_chunk(doc, min_chars):
                    continue
                norm = " ".join((doc or "").split()).lower()[:200]
                if norm in seen_norm:
                    continue
                seen_norm.add(norm)

                kept.append({
                    "block_id": block_id,
                    "text": doc,
                    "metadata": meta,
                    "score": round(1.0 - min(dist, 1.0), 4),  # cosine → similarity
                })
                if len(kept) >= top_k:
                    break
        return kept

    # ITU front-matter boilerplate that is duplicated across nearly every
    # document (1900-4400x in the corpus) and carries no query-relevant content.
    _BOILERPLATE = (
        "role of the radiocommunication sector",
        "common patent policy",
        "regulatory and policy functions",
        "all rights reserved",
        "reproduced by permission of itu",
        "electronic publication geneva",
    )

    @staticmethod
    def _is_junk_chunk(text: str, min_chars: int) -> bool:
        """True for page headers/footers, ITU boilerplate, and other non-substantive chunks."""
        t = " ".join((text or "").split())
        if len(t) < min_chars:
            return True
        if re.fullmatch(r"(Rec\.?\s+)?ITU[-\s]?R\s+[A-Z]{1,3}\.?\d+[\d\-.]*", t, re.IGNORECASE):
            return True
        # duplicated ITU front-matter boilerplate
        low = t.lower()
        if any(b in low for b in ChromaStore._BOILERPLATE):
            return True
        return False

    def count(self) -> int:
        return self._get_collection().count()

    def clear(self):
        try:
            self._client.delete_collection(self._collection_name)
        except Exception:
            pass
        self._collection = None

    # ── internal ──

    def _get_collection(self):
        if self._collection is not None:
            return self._collection

        _disable_chroma_posthog_telemetry()

        import chromadb
        from chromadb.config import Settings

        chroma_settings = Settings(anonymized_telemetry=False)
        if self._persist_dir:
            Path(self._persist_dir).mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(
                path=self._persist_dir,
                settings=chroma_settings,
            )
        else:
            self._client = chromadb.Client(settings=chroma_settings)

        try:
            self._collection = self._client.get_collection(self._collection_name)
        except Exception:
            self._collection = self._client.create_collection(
                name=self._collection_name,
                metadata={"hnsw:space": "cosine"},
            )
        return self._collection

    @staticmethod
    def _block_metadata(block: SpectrumContentBlock) -> dict:
        """Extract Chroma-safe metadata (only str/int/float/bool values)."""
        meta = block.metadata.copy()
        meta["doc_id"] = block.doc_id
        meta["source_path"] = block.source_path
        meta["page_idx"] = block.page_idx
        meta["block_type"] = block.block_type
        if block.section_path:
            meta["section_path"] = " > ".join(block.section_path)
        # Chroma only supports str/int/float/bool; flatten lists
        for key in list(meta):
            if isinstance(meta[key], list):
                meta[key] = ", ".join(str(v) for v in meta[key])
            elif meta[key] is None:
                meta[key] = ""
        return meta
