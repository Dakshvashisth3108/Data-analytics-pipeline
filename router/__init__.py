"""Hybrid intent-routing layer over the SQL engine and the RAG retriever.

A user question flows through:
    intent.IntentClassifier        ->  pick SQL / RAG / both / decline
    rag_retriever.RagRetriever     ->  semantic chunk lookup (ChromaDB)
    nl2sql.NL2SQLEngine            ->  precise SQL on Gold parquet
    synthesizer.AnswerSynthesizer  ->  LLM merges results into one answer
    router.HybridRouter            ->  orchestrator (the public API)
"""
from .intent       import ClassificationResult, Intent
from .classifier   import IntentClassifier
from .rag_retriever import RagRetriever, RetrievedChunk
from .conversation import Conversation, Turn
from .synthesizer  import AnswerSynthesizer
from .router       import HybridRouter, RouterResponse

__all__ = [
    "AnswerSynthesizer",
    "ClassificationResult",
    "Conversation",
    "HybridRouter",
    "Intent",
    "IntentClassifier",
    "RagRetriever",
    "RetrievedChunk",
    "RouterResponse",
    "Turn",
]
