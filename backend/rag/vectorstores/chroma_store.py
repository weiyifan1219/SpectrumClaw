"""Chroma vector store — block-level embedding index with metadata filtering."""

from __future__ import annotations

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
        """Embed and store blocks in Chroma."""
        if not blocks:
            return
        col = self._get_collection()
        texts = [b.enhanced_content or b.content for b in blocks]
        embeddings = self._embedding_provider.embed_texts(texts)
        ids = [b.block_id for b in blocks]
        metadatas = [self._block_metadata(b) for b in blocks]

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
    ) -> list[dict]:
        """Search for top-k blocks matching query. Returns list of {block_id, metadata, score}."""
        col = self._get_collection()
        query_embedding = self._embedding_provider.embed_query(query)

        results = col.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=where,
            include=["metadatas", "documents", "distances"],
        )

        out = []
        if results["ids"] and results["ids"][0]:
            for i, block_id in enumerate(results["ids"][0]):
                meta = results["metadatas"][0][i] if results["metadatas"] else {}
                doc = results["documents"][0][i] if results["documents"] else ""
                dist = results["distances"][0][i] if results["distances"] else 0
                out.append({
                    "block_id": block_id,
                    "text": doc,
                    "metadata": meta,
                    "score": round(1.0 - min(dist, 1.0), 4),  # cosine → similarity
                })
        return out

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
