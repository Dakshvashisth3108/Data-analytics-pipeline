"""Auto-repair common LLM hallucinations in generated SQL.

Small models (Gemma 2B) routinely write ``FROM attrition`` when the
real view is ``attrition_by_country``. Rather than failing validation,
we try a deterministic fix:

    1. Parse the SQL with sqlglot.
    2. For each table reference that's NOT in the allowed view list,
       look for views whose name starts with ``<bare>_``.
    3. Score each candidate by keyword overlap with the user's
       question (e.g. "country" in the question -> picks
       ``attrition_by_country`` over ``attrition_by_department``).
    4. If a candidate scores > 0, rewrite the table node.

The rewrite happens before validation, so an unfixable hallucination
still gets cleanly rejected by the validator with a useful error
message. We never silently swap in a table the user didn't intend.
"""
from __future__ import annotations

import re

import sqlglot
from sqlglot import expressions as exp


_WORD_RE = re.compile(r"[a-z0-9]+")


def _question_words(question: str) -> set[str]:
    return set(_WORD_RE.findall((question or "").lower()))


def repair_bare_tables(
    sql: str,
    question: str,
    allowed_views: list[str],
) -> tuple[str, list[tuple[str, str]]]:
    """Rewrite bare table refs to a real view based on keyword overlap.

    Returns ``(maybe_rewritten_sql, remap)`` where ``remap`` is a list
    of ``(old_name, new_name)`` pairs actually applied. Empty list
    means nothing changed.
    """
    if not sql or not allowed_views:
        return sql, []

    allowed_set = set(allowed_views)
    if not allowed_set:
        return sql, []

    try:
        tree = sqlglot.parse_one(sql, read="duckdb")
    except Exception:
        return sql, []  # parser will fail in validate_sql; surface there

    q_words = _question_words(question)
    remap: list[tuple[str, str]] = []

    for table in tree.find_all(exp.Table):
        bare = table.name
        if not bare or bare in allowed_set:
            continue

        # Look for views starting with this prefix (e.g. "attrition" ->
        # attrition_by_country, attrition_by_department, ...)
        candidates = [v for v in allowed_views if v.startswith(bare + "_")]
        if not candidates:
            continue

        # Score each by overlap of its suffix tokens with question words
        scored: list[tuple[str, int]] = []
        prefix_parts = bare.split("_")
        for cand in candidates:
            suffix_parts = cand.split("_")[len(prefix_parts):]
            score = sum(1 for tok in suffix_parts if tok in q_words)
            scored.append((cand, score))

        # Pick the best scoring; tie-break by shortest suffix (most specific)
        scored.sort(key=lambda x: (-x[1], len(x[0])))
        best, best_score = scored[0]
        if best_score <= 0:
            # No keyword overlap; safer to let the validator reject so
            # the user (and the synth LLM) sees the real problem.
            continue

        # Rewrite the table in-place
        table.set("this", exp.to_identifier(best))
        remap.append((bare, best))

    if not remap:
        return sql, []
    rewritten = tree.sql(dialect="duckdb")
    return rewritten, remap
