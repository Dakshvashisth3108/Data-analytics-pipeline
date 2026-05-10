"""HybridRouter -- the public face of the conversational analytics layer.

Given a free-form question + optional conversation history:

    1. classify intent (rule, then LLM if ambiguous)
    2. dispatch:
         ANALYTICAL  -> nl2sql only
         SEMANTIC    -> rag only
         HYBRID      -> both, in parallel-ish (sequential is fine; SQL is
                        very fast on Gold parquet, RAG is local too)
         OFFTOPIC    -> short polite decline
    3. synthesise a natural-language answer with the LLM
    4. record a one-line summary in conversation memory
    5. return a structured RouterResponse with timings + sources

Every step has its own try/except so a failure in one engine still
produces a usable response.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

from nl2sql import NL2SQLEngine
from nl2sql.engine import AnswerResult as SQLAnswer
from utils import Config, get_logger, load_config

from .classifier   import IntentClassifier
from .conversation import Conversation, Turn
from .intent       import ClassificationResult, Intent
from .rag_retriever import RagRetriever, RetrievedChunk
from .synthesizer  import AnswerSynthesizer

LOG = get_logger("hcm.router")


@dataclass
class RouterResponse:
    question: str
    intent: str
    intent_confidence: float
    intent_source: str
    intent_reason: str

    answer_text: str = ""
    sql: str | None = None
    sql_columns: list[str] = field(default_factory=list)
    sql_rows: list[dict[str, Any]] = field(default_factory=list)
    sql_row_count: int = 0
    sql_raw_model_output: str | None = None   # raw LLM SQL response (for debugging)
    sql_error: str | None = None              # SQL-stage error (separate from top-level)
    rag_chunks: list[dict[str, Any]] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)

    elapsed_ms_total: int = 0
    elapsed_ms_classify: int = 0
    elapsed_ms_sql: int = 0
    elapsed_ms_rag: int = 0
    elapsed_ms_synth: int = 0

    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class HybridRouter:
    def __init__(self,
                 cfg: Config | None = None,
                 classifier: IntentClassifier | None = None,
                 sql_engine: NL2SQLEngine | None = None,
                 retriever: RagRetriever | None = None,
                 synthesizer: AnswerSynthesizer | None = None,
                 conversation: Conversation | None = None) -> None:
        self.cfg = cfg or load_config()
        rcfg = self.cfg.get("router") or {}

        self.classifier   = classifier   # may be None until wired
        self.sql_engine   = sql_engine
        self.retriever    = retriever
        self.synthesizer  = synthesizer  or AnswerSynthesizer()
        self.conversation = conversation or Conversation(
            max_turns=int((rcfg.get("conversation") or {}).get("history_turns", 6)),
        )

        rag_cfg = (rcfg.get("rag") or {})
        self._rag_top_k = int(rag_cfg.get("top_k", 5))

    # ── public API ───────────────────────────────────────────────────────
    def ask(self, question: str) -> RouterResponse:
        t0 = time.perf_counter()
        resp = RouterResponse(
            question=question,
            intent=Intent.SEMANTIC.value,
            intent_confidence=0.0,
            intent_source="none",
            intent_reason="",
        )

        # 1. Classify
        t1 = time.perf_counter()
        try:
            cls = self.classifier.classify(question, history=self.conversation) \
                if self.classifier else ClassificationResult(
                    intent=Intent.SEMANTIC, confidence=0.3, source="fallback",
                    reason="no classifier configured")
        except Exception as exc:  # pragma: no cover - defensive
            LOG.exception("classifier_failed")
            resp.error = f"classifier failed: {exc}"
            resp.elapsed_ms_total = int((time.perf_counter() - t0) * 1000)
            return resp
        resp.elapsed_ms_classify = int((time.perf_counter() - t1) * 1000)
        resp.intent             = cls.intent.value
        resp.intent_confidence  = cls.confidence
        resp.intent_source      = cls.source
        resp.intent_reason      = cls.reason

        LOG.info("routed q=%r intent=%s conf=%.2f via=%s",
                 question[:80], cls.intent.value, cls.confidence, cls.source)

        # 2. Dispatch
        sql_answer: SQLAnswer | None = None
        chunks: list[RetrievedChunk] = []

        if cls.needs_sql:
            if self.sql_engine is None:
                LOG.warning("intent_needs_sql_but_engine_missing")
            else:
                t2 = time.perf_counter()
                try:
                    sql_answer = self.sql_engine.ask(question)
                except Exception as exc:
                    LOG.exception("sql_engine_failed")
                    sql_answer = None
                    resp.error = f"sql engine failed: {exc}"
                resp.elapsed_ms_sql = int((time.perf_counter() - t2) * 1000)

        if cls.needs_rag:
            if self.retriever is None or not self.retriever.is_ready():
                LOG.warning("intent_needs_rag_but_index_missing")
            else:
                t3 = time.perf_counter()
                try:
                    chunks = self.retriever.retrieve(
                        question, top_k=self._rag_top_k,
                    )
                except Exception:
                    LOG.exception("rag_retrieve_failed")
                    chunks = []
                resp.elapsed_ms_rag = int((time.perf_counter() - t3) * 1000)

        # 3. Synthesise
        t4 = time.perf_counter()
        try:
            answer_text, synth_ms = self.synthesizer.synthesize(
                question=question, intent=cls.intent,
                sql_result=sql_answer, chunks=chunks,
                history=self.conversation,
            )
        except Exception as exc:  # pragma: no cover
            LOG.exception("synthesize_failed")
            answer_text = f"(synthesis failed: {exc})"
            synth_ms = 0
        resp.elapsed_ms_synth = max(synth_ms, int((time.perf_counter() - t4) * 1000))
        resp.answer_text = answer_text

        # 4. Populate response payload
        if sql_answer is not None:
            resp.sql                   = sql_answer.sql
            resp.sql_columns           = sql_answer.columns
            resp.sql_rows              = sql_answer.rows[:50]   # cap payload
            resp.sql_row_count         = sql_answer.row_count
            resp.sql_raw_model_output  = sql_answer.raw_model_output
            resp.sql_error             = sql_answer.error
            resp.sources.extend(sql_answer.referenced_tables)
        if chunks:
            resp.rag_chunks = [
                {"chunk_id": c.chunk_id, "text": c.text,
                 "similarity": c.similarity, "metadata": c.metadata}
                for c in chunks
            ]
            resp.sources.extend(c.chunk_id for c in chunks)

        # 5. Persist to history
        summary = AnswerSynthesizer.summary_for_history(sql_answer, chunks)
        self.conversation.add(Turn(
            question=question,
            answer_summary=summary,
            intent=cls.intent.value,
        ))

        resp.elapsed_ms_total = int((time.perf_counter() - t0) * 1000)
        LOG.info(
            "completed intent=%s total_ms=%d (cls=%d sql=%d rag=%d synth=%d) sources=%s",
            cls.intent.value, resp.elapsed_ms_total, resp.elapsed_ms_classify,
            resp.elapsed_ms_sql, resp.elapsed_ms_rag, resp.elapsed_ms_synth,
            len(resp.sources),
        )
        return resp

    # ── lifecycle ───────────────────────────────────────────────────────
    def reset_conversation(self) -> None:
        self.conversation.clear()

    def close(self) -> None:
        if self.sql_engine is not None:
            try:
                self.sql_engine.close()
            except Exception:
                pass


# ── default factory ──────────────────────────────────────────────────────
def build_default_router(cfg: Config | None = None) -> HybridRouter:
    """Wire up production defaults: rule+LLM classifier, NL2SQL engine,
    ChromaDB RAG, LLM synthesizer. Each is lazy so missing pieces (e.g.
    no Ollama, no Chroma yet) degrade rather than crash."""
    cfg = cfg or load_config()

    # Build Ollama client (shared by classifier + synthesizer)
    ollama = None
    try:
        from nl2sql.ollama_client import OllamaClient
        ocfg = cfg.get("nl2sql.ollama") or {}
        ollama = OllamaClient(
            base_url=str(ocfg.get("base_url", "http://localhost:11434")),
            model=str(ocfg.get("model", "gemma2:2b")),
            timeout_seconds=int(ocfg.get("timeout_seconds", 120)),
            temperature=float(ocfg.get("temperature", 0.1)),
            num_predict=int(ocfg.get("num_predict", 512)),
        )
    except Exception:
        LOG.warning("ollama_client_init_failed; using rule-only classifier "
                    "and fallback synthesizer")

    classifier = IntentClassifier(
        ollama_client=ollama,
        enable_rule_tier=True,
        enable_llm_tier=ollama is not None,
    )

    # NL2SQL engine (needs Gold parquet)
    sql_engine: NL2SQLEngine | None = None
    try:
        sql_engine = NL2SQLEngine(cfg=cfg, ollama=ollama)
    except Exception:
        LOG.warning("nl2sql_engine_init_failed; analytical questions degraded")

    # RAG retriever (needs ChromaDB + embedder)
    retriever: RagRetriever | None = None
    try:
        from embeddings import ChromaStore, Embedder
        ecfg = cfg.get("embeddings") or {}
        store = ChromaStore(
            persist_dir=str(ecfg.get("vectors_dir", "data/vectors/chroma")),
            collection_name=str(ecfg.get("collection_name", "hcm_insights")),
        )
        embedder = Embedder(model_name=str(ecfg.get("model",
                                "sentence-transformers/all-MiniLM-L6-v2")))
        rcfg = (cfg.get("router.rag") or {})
        retriever = RagRetriever(
            store=store, embedder=embedder,
            default_top_k=int(rcfg.get("top_k", 5)),
            min_similarity=float(rcfg.get("min_similarity", 0.0)),
        )
    except Exception:
        LOG.warning("rag_retriever_init_failed; semantic questions degraded")

    synthesizer = AnswerSynthesizer(
        ollama_client=ollama,
        max_output_chars=int((cfg.get("router.synthesizer") or {})
                              .get("max_output_chars", 1200)),
    )

    return HybridRouter(
        cfg=cfg,
        classifier=classifier,
        sql_engine=sql_engine,
        retriever=retriever,
        synthesizer=synthesizer,
    )
