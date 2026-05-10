"""Semantic embedding pipeline for HCM Gold marts.

Reads Gold parquet aggregates, produces business-insight text chunks,
embeds them with sentence-transformers, and persists to ChromaDB for
RAG retrieval.

Public API:
    from embeddings import Chunk, Embedder, ChromaStore
"""
from .chunk import Chunk
from .embedder import Embedder
from .vectorstore import ChromaStore

__all__ = ["Chunk", "Embedder", "ChromaStore"]
