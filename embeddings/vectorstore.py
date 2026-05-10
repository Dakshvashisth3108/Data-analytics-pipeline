"""ChromaDB wrapper.

ChromaDB's PersistentClient writes a SQLite + index folder on disk so the
collection survives restarts. We use cosine similarity (matches the
normalized embeddings we get from sentence-transformers) and key chunks
by their stable ``chunk_id`` so re-running upserts in place rather than
duplicating.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from utils import get_logger

from .chunk import Chunk

if TYPE_CHECKING:
    from chromadb import Collection, ClientAPI

LOG = get_logger("hcm.embeddings.vectorstore")


class ChromaStore:
    """Thin wrapper over a ChromaDB persistent collection."""

    def __init__(self,
                 persist_dir: str | Path,
                 collection_name: str = "hcm_insights") -> None:
        self.persist_dir = Path(persist_dir).resolve()
        self.collection_name = collection_name
        self._client: ClientAPI | None = None
        self._collection: Collection | None = None

    # ── lifecycle ────────────────────────────────────────────────────────
    def _ensure_open(self) -> "Collection":
        if self._collection is not None:
            return self._collection

        import chromadb
        from chromadb.config import Settings

        self.persist_dir.mkdir(parents=True, exist_ok=True)
        LOG.info("opening_chroma path=%s collection=%s",
                 self.persist_dir, self.collection_name)
        self._client = chromadb.PersistentClient(
            path=str(self.persist_dir),
            settings=Settings(anonymized_telemetry=False),
        )
        self._collection = self._client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        return self._collection

    def count(self) -> int:
        return self._ensure_open().count()

    # ── writes ───────────────────────────────────────────────────────────
    def upsert(self, chunks: list[Chunk],
               embeddings: list[list[float]]) -> None:
        """Insert-or-replace chunks by their ``chunk_id``."""
        if len(chunks) != len(embeddings):
            raise ValueError(
                f"chunks/embeddings length mismatch: {len(chunks)} vs {len(embeddings)}"
            )
        if not chunks:
            return
        col = self._ensure_open()
        col.upsert(
            ids=[c.chunk_id for c in chunks],
            documents=[c.text for c in chunks],
            metadatas=[c.metadata for c in chunks],
            embeddings=embeddings,
        )
        LOG.info("upserted count=%d (collection_total=%d)",
                 len(chunks), col.count())

    def delete_by_metadata(self, where: dict[str, Any]) -> None:
        """Delete chunks matching a metadata filter (e.g. {'domain': 'attrition'})."""
        col = self._ensure_open()
        col.delete(where=where)

    def reset(self) -> None:
        """Drop the entire collection. Use with care."""
        col = self._ensure_open()
        ids = col.get()["ids"]
        if ids:
            col.delete(ids=ids)
            LOG.info("collection_reset deleted=%d", len(ids))

    # ── reads ────────────────────────────────────────────────────────────
    def query(self, query_text: str, embedder, n_results: int = 5,
              where: dict[str, Any] | None = None) -> dict[str, Any]:
        """Retrieve the n most similar chunks for a natural-language query.

        ``embedder`` is the Embedder instance used to vectorise the query.
        """
        emb = embedder.embed([query_text])[0]
        col = self._ensure_open()
        return col.query(
            query_embeddings=[emb],
            n_results=n_results,
            where=where,
        )
