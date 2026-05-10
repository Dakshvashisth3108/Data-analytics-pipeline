"""Compose the final natural-language answer from SQL rows + RAG chunks.

The synthesizer is intent-aware:

* ANALYTICAL  -> prompt the LLM to summarise the SQL rows in 2-3 lines
* SEMANTIC    -> prompt the LLM to paraphrase the RAG chunks
* HYBRID      -> prompt the LLM with BOTH (rows + chunks) and ask for an
                  insight that ties them together
* OFFTOPIC    -> no LLM call; return a polite scope reminder

If the LLM is unavailable we fall back to a deterministic template so
the chat experience degrades gracefully rather than 500-ing.
"""
from __future__ import annotations

from typing import Any

from utils import get_logger

from .conversation import Conversation
from .intent import Intent
from .rag_retriever import RetrievedChunk, format_chunks_for_prompt

LOG = get_logger("hcm.router.synth")

_OFFTOPIC_REPLY = (
    "I can only answer questions about your HCM analytics "
    "(workforce, attrition, salary, performance, hiring). "
    "Try something like 'which department has the highest attrition?'"
)

_SYSTEM_PROMPT = (
    "You are a concise HR analytics assistant. Answer the user's "
    "question using ONLY the SQL result and context provided. "
    "Cite specific numbers from the SQL when relevant. Keep the answer "
    "to 1-4 sentences unless the user asked for detail. Do not invent "
    "data not present in the inputs."
)


def _format_sql_block(sql_result) -> str:
    """Render a SQL AnswerResult as a compact ASCII table for the prompt.

    When the SQL ran but returned 0 rows we surface the actual query
    so the LLM can either accept "no matches" as the answer OR (more
    useful for small models) realise it picked the wrong table.
    """
    if sql_result is None:
        return "(no SQL result)"
    if sql_result.error:
        return f"(SQL error: {sql_result.error})\nGenerated SQL: {sql_result.sql or '-'}"
    if sql_result.cannot_answer:
        return "(SQL engine declined: " + (sql_result.sql or "")[:200] + ")"
    if not sql_result.rows:
        return (
            f"SQL ran successfully but returned 0 rows.\n"
            f"Generated SQL: {sql_result.sql or '-'}\n"
            f"Referenced tables: {sql_result.referenced_tables}"
        )
    cols = sql_result.columns
    head = " | ".join(cols)
    rows = "\n".join(
        " | ".join(str(r.get(c, "")) for c in cols)
        for r in sql_result.rows[:30]
    )
    truncated = "" if sql_result.row_count <= 30 else \
        f"\n(... {sql_result.row_count - 30} more rows truncated for prompt)"
    return f"SQL ({sql_result.row_count} rows):\n{head}\n{rows}{truncated}"


def _short_summary_for_history(sql_result, chunks: list[RetrievedChunk]) -> str:
    """Generate a compact one-liner suitable for storing in history."""
    if sql_result is not None and sql_result.rows:
        first = sql_result.rows[0]
        kv = ", ".join(f"{k}={v}" for k, v in list(first.items())[:3])
        more = "" if sql_result.row_count <= 1 else f" (+{sql_result.row_count-1} rows)"
        return f"[SQL] {kv}{more}"
    if chunks:
        return f"[RAG] top: {chunks[0].text[:160]}"
    return "(no result)"


class AnswerSynthesizer:
    def __init__(self, ollama_client=None,
                 max_output_chars: int = 1200) -> None:
        self.ollama = ollama_client
        self.max_output_chars = int(max_output_chars)

    # ── deterministic fallback (no LLM) ──────────────────────────────────
    def _fallback_text(self, intent: Intent, sql_result,
                       chunks: list[RetrievedChunk]) -> str:
        if intent is Intent.OFFTOPIC:
            return _OFFTOPIC_REPLY
        parts: list[str] = []
        if sql_result is not None and sql_result.rows:
            first = sql_result.rows[0]
            parts.append(
                "Top result: " + ", ".join(f"{k}={v}" for k, v in first.items())
                + f" (out of {sql_result.row_count} rows)."
            )
        if chunks:
            parts.append("Context: " + chunks[0].text[:300])
        if not parts:
            return ("I couldn't find an answer in your HCM data. "
                    "Try rephrasing or run the pipeline if it hasn't been "
                    "executed yet.")
        return " ".join(parts)

    # ── LLM-powered synthesis ────────────────────────────────────────────
    def synthesize(self, *, question: str, intent: Intent,
                   sql_result=None,
                   chunks: list[RetrievedChunk] | None = None,
                   history: Conversation | None = None) -> tuple[str, int]:
        chunks = chunks or []

        # Short-circuit offtopic without spending an LLM call
        if intent is Intent.OFFTOPIC:
            return _OFFTOPIC_REPLY, 0

        if self.ollama is None:
            return self._fallback_text(intent, sql_result, chunks), 0

        sections: list[str] = []
        if history is not None:
            ctx = history.render(n=3)
            if ctx:
                sections.append(ctx)

        sections.append(f"User question: {question.strip()}")
        sections.append("")
        sections.append(_format_sql_block(sql_result))
        sections.append("")
        sections.append("Background context (semantic):")
        sections.append(format_chunks_for_prompt(chunks))

        if intent is Intent.ANALYTICAL:
            sections.append(
                "\nAnswer the question using the SQL result above. "
                "Cite specific numbers; do not speculate beyond the rows shown. "
                "If the SQL returned 0 rows, DO NOT claim the dataset lacks "
                "the requested information -- the data is present; the query "
                "simply didn't match. Tell the user 'the SQL returned no "
                "matches' and suggest they rephrase the question."
            )
        elif intent is Intent.SEMANTIC:
            sections.append(
                "\nAnswer the question using the background context above. "
                "If multiple chunks overlap, synthesise rather than repeat."
            )
        else:  # HYBRID
            sections.append(
                "\nAnswer using BOTH the SQL result (for numbers) AND the "
                "background context (for the 'why'). Explicitly tie them "
                "together in 2-4 sentences."
            )

        prompt = "\n".join(sections)
        try:
            gen = self.ollama.generate(prompt, system=_SYSTEM_PROMPT)
            text = (gen.text or "").strip()
            if not text:
                text = self._fallback_text(intent, sql_result, chunks)
            if len(text) > self.max_output_chars:
                text = text[: self.max_output_chars].rstrip() + "..."
            return text, gen.elapsed_ms
        except Exception:
            LOG.exception("synthesize_failed")
            return self._fallback_text(intent, sql_result, chunks), 0

    # ── helper for conversation memory ───────────────────────────────────
    @staticmethod
    def summary_for_history(sql_result, chunks: list[RetrievedChunk]) -> str:
        return _short_summary_for_history(sql_result, chunks)
