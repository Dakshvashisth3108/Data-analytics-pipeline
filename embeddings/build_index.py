"""Embedding index builder — Gold parquet -> ChromaDB.

Orchestrator that reads each Gold mart, runs the appropriate chunker to
produce business-insight text, embeds those chunks with sentence-
transformers, and upserts everything into a persistent ChromaDB
collection.

Run from the project root (Windows PowerShell or any shell):

    python -m embeddings.build_index                 # full rebuild
    python -m embeddings.build_index --reset         # drop + rebuild
    python -m embeddings.build_index --query "..."   # quick sanity check
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# sys.path bootstrap so this can be invoked directly too.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from utils import get_logger, load_config

from embeddings.chunkers import (
    build_attrition, build_overview, build_performance,
    build_salary, build_workforce,
)
from embeddings.embedder import Embedder
from embeddings.vectorstore import ChromaStore

LOG = get_logger("hcm.embeddings.build")


CHUNKER_REGISTRY = [
    ("overview",    build_overview),
    ("attrition",   build_attrition),
    ("salary",      build_salary),
    ("workforce",   build_workforce),
    ("performance", build_performance),
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Build/refresh the HCM RAG index from Gold parquet marts.",
    )
    p.add_argument("--reset", action="store_true",
                   help="Drop the entire collection before re-indexing.")
    p.add_argument("--query", type=str, default=None,
                   help="After indexing, run a sample similarity query.")
    p.add_argument("--top-k", type=int, default=5,
                   help="Top-K chunks to return for --query (default 5).")
    p.add_argument("--no-write", action="store_true",
                   help="Generate + log chunks but skip embedding/writing.")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    cfg = load_config()
    e_cfg = cfg.embeddings

    LOG.info(
        "embedding_pipeline model=%s store=%s collection=%s reset=%s",
        e_cfg.model, e_cfg.vectors_dir, e_cfg.collection_name, args.reset,
    )

    # ── 1. Gather chunks ────────────────────────────────────────────────
    all_chunks = []
    per_domain_counts: dict[str, int] = {}
    for domain_label, build_fn in CHUNKER_REGISTRY:
        try:
            chunks = build_fn()
        except Exception:
            LOG.exception("chunker_failed domain=%s", domain_label)
            continue
        per_domain_counts[domain_label] = len(chunks)
        LOG.info("chunked domain=%s count=%d", domain_label, len(chunks))
        all_chunks.extend(chunks)

    if not all_chunks:
        LOG.warning("no_chunks_built — has the Gold pipeline run? "
                    "(`python -m gold.gold_etl`)")
        return 2

    LOG.info("total_chunks=%d breakdown=%s",
             len(all_chunks), per_domain_counts)

    if args.no_write:
        LOG.info("no_write=true — skipping embedding/upsert")
        # Print a sample for the operator
        for c in all_chunks[:3]:
            LOG.info("sample chunk_id=%s text=%s", c.chunk_id, c.text[:140])
        return 0

    # ── 2. Embed in batches ─────────────────────────────────────────────
    try:
        embedder = Embedder(model_name=str(e_cfg.model))
        texts = [c.text for c in all_chunks]
        batch_size = int(cfg.get("embeddings.batch_size", 32))
        LOG.info("embedding count=%d batch_size=%d", len(texts), batch_size)
        vectors = embedder.embed(texts, batch_size=batch_size)
        LOG.info("embedded count=%d dim=%d", len(vectors), len(vectors[0]))
    except Exception:
        LOG.exception("embedding_phase_failed")
        return 3

    # ── 3. Persist to Chroma ────────────────────────────────────────────
    try:
        store = ChromaStore(
            persist_dir=str(e_cfg.vectors_dir),
            collection_name=str(e_cfg.collection_name),
        )
        if args.reset:
            store.reset()
        store.upsert(all_chunks, vectors)
    except Exception:
        LOG.exception("vectorstore_write_failed")
        return 4

    # ── 4. Optional smoke query ─────────────────────────────────────────
    if args.query:
        try:
            results = store.query(args.query, embedder, n_results=args.top_k)
            LOG.info("query=%r top_k=%d", args.query, args.top_k)
            ids = results.get("ids", [[]])[0]
            docs = results.get("documents", [[]])[0]
            distances = results.get("distances", [[]])[0]
            for rank, (cid, doc, dist) in enumerate(zip(ids, docs, distances), 1):
                score = 1.0 - float(dist)  # cosine distance -> similarity
                LOG.info(
                    "result rank=%d score=%.3f id=%s text=%s",
                    rank, score, cid, (doc[:160] + "...") if len(doc) > 160 else doc,
                )
        except Exception:
            LOG.exception("query_failed")
            return 5

    LOG.info("done collection_size=%d", store.count())
    return 0


if __name__ == "__main__":
    sys.exit(main())
