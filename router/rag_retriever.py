"""Thin retrieval wrapper over ChromaStore + Embedder.

The vector store and embedder live in the ``embeddings`` package.
This module just exposes a tidy ``RagRetriever.retrieve(query, k=...)``
that returns typed ``RetrievedChunk`` objects sorted by similarity, so
the router and synthesizer don't have to know about Chroma's dict API.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from embeddings import ChromaStore, Embedder

from utils import get_logger

LOG = get_logger("hcm.router.rag")


@dataclass
class RetrievedChunk:
    chunk_id: str
    text: str
    similarity: float
    metadata: dict[str, Any] = field(default_factory=dict)


class RagRetriever:
    def __init__(self, store: ChromaStore | None = None,
                 embedder: Embedder | None = None,
                 default_top_k: int = 5,
                 min_similarity: float = 0.0) -> None:
        self.store = store
        self.embedder = embedder
        self.default_top_k = int(default_top_k)
        self.min_similarity = float(min_similarity)

    def is_ready(self) -> bool:
        if self.store is None or self.embedder is None:
            return False
        try:
            return self.store.count() > 0
        except Exception:
            return False

    def retrieve(self, query: str, *,
                 top_k: int | None = None,
                 where: dict[str, Any] | None = None) -> list[RetrievedChunk]:
        if not query or self.store is None or self.embedder is None:
            return []

        k = top_k or self.default_top_k
        try:
            raw = self.store.query(query, self.embedder, n_results=k, where=where)
        except Exception:
            LOG.exception("rag_query_failed query=%r", query[:80])
            return []

        # Chroma returns lists-of-lists keyed by ['ids','documents','metadatas','distances'],
        # one entry per query embedding. We send a single query so [0] is the result.
        ids        = (raw.get("ids")        or [[]])[0]
        docs       = (raw.get("documents")  or [[]])[0]
        metas      = (raw.get("metadatas")  or [[]])[0]
        distances  = (raw.get("distances")  or [[]])[0]

        out: list[RetrievedChunk] = []
        for cid, doc, meta, dist in zip(ids, docs, metas, distances):
            # cosine distance -> similarity in [0..2] -> clamp to [0..1] using 1-d
            sim = max(0.0, 1.0 - float(dist))
            if sim < self.min_similarity:
                continue
            out.append(RetrievedChunk(
                chunk_id=str(cid),
                text=str(doc or ""),
                similarity=sim,
                metadata=dict(meta or {}),
            ))
        LOG.info("rag_retrieved n=%d query_chars=%d", len(out), len(query))
        return out


def format_chunks_for_prompt(chunks: list[RetrievedChunk],
                             max_chars: int = 2500) -> str:
    """Render retrieved chunks as a bulleted block for the synthesizer."""
    if not chunks:
        return "(no relevant chunks retrieved)"
    lines: list[str] = []
    used = 0
    for c in chunks:
        line = f"- [{c.chunk_id} | sim={c.similarity:.2f}] {c.text}"
        if used + len(line) > max_chars:
            break
        lines.append(line)
        used += len(line)
    return "\n".join(lines)
