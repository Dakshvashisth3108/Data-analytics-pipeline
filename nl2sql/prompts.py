"""Prompt templates for the SQL generation step.

The system prompt is fixed; the user prompt mixes in the schema doc
(produced by SchemaCatalog.to_prompt_doc) and the actual question.

The model (Gemma 2B is small, ~1.5 GB quantised) needs unambiguous
instructions or it'll happily hallucinate column names. We:

* enumerate every available view + columns,
* hard-rule "use ONLY these tables/columns",
* fence the SQL output so we can extract it deterministically,
* provide an explicit CANNOT_ANSWER escape hatch.
"""
from __future__ import annotations

import re

SYSTEM_PROMPT = """You are a careful data analyst. Translate the user's
question into a single DuckDB-compatible SELECT (or WITH/SELECT) query.

Rules:
- Output ONLY the SQL inside a fenced code block: ```sql ... ```
- Use ONLY the tables and columns listed in the schema below.
- Do NOT invent columns or tables. If a needed concept is missing,
  output the literal: ```sql
  -- CANNOT_ANSWER: <one-line reason>
  ```
- Always include a LIMIT clause (use 100 if unsure).
- No INSERT, UPDATE, DELETE, DROP, ATTACH, COPY, INSTALL, LOAD,
  PRAGMA, or SET statements. Read-only queries only.
- Prefer aggregates and ORDER BY for "top/bottom" questions.
- Identifier casing matches the schema exactly.
"""


def build_user_prompt(schema_doc: str, question: str) -> str:
    return (
        f"{schema_doc}\n\n"
        f"Question: {question.strip()}\n\n"
        f"Return only the SQL inside a ```sql fenced block.\n"
    )


# ── Output extraction ────────────────────────────────────────────────────
_FENCE_RE = re.compile(
    r"```(?:sql)?\s*(?P<sql>.+?)\s*```",
    re.DOTALL | re.IGNORECASE,
)


def extract_sql(model_text: str) -> str:
    """Pull the SQL out of the fenced block. Falls back to the raw text
    if no fence is present (Gemma sometimes forgets the fences)."""
    if not model_text:
        return ""
    m = _FENCE_RE.search(model_text)
    if m:
        return m.group("sql").strip()
    # Fallback — strip leading prose lines and treat the rest as SQL.
    lines = [ln for ln in model_text.splitlines() if ln.strip()]
    if lines and lines[0].lower().startswith(("here", "the sql", "this query")):
        lines = lines[1:]
    return "\n".join(lines).strip()


def is_cannot_answer(sql: str) -> bool:
    return "CANNOT_ANSWER" in (sql or "").upper()
