"""Prompt templates for the SQL generation step.

Small models like Gemma 2B follow CONCRETE EXAMPLES far better than
abstract rules, so the prompt is built in three parts:

1. ``SYSTEM_PROMPT`` -- terse rules.
2. ``FEW_SHOT_EXAMPLES`` -- 4 question -> SQL pairs covering the
   common analytical patterns (lowest, highest, by-group, all-rows).
   The example table names match real views in the catalogue so the
   model has a concrete anchor.
3. The runtime user message: schema doc + the actual question.

Without the examples, Gemma 2B routinely hallucinates ORDER BY
direction, drops the LIMIT, or invents column names. With them, it
mirrors the shape it just saw.
"""
from __future__ import annotations

import re

SYSTEM_PROMPT = """You are a careful data analyst. Translate the user's
question into a single DuckDB-compatible SELECT (or WITH/SELECT) query.

CRITICAL TABLE NAMING RULE
==========================
Every table name in this database follows the pattern
`<domain>_<metric>` (with underscore). There is NEVER a bare table
called `attrition`, `salary`, `workforce`, or `performance`.

Wrong:   FROM attrition          FROM salary             FROM performance
Right:   FROM attrition_by_country
         FROM salary_by_department
         FROM performance_top_teams
         (etc., as listed in the schema below)

If you write a bare name like `FROM attrition`, the query WILL FAIL.

Other rules
-----------
- Output ONLY the SQL inside a fenced code block: ```sql ... ```
- Use ONLY the tables and columns listed in the schema below.
- Do NOT invent columns or tables. If a needed concept is missing,
  output the literal: ```sql
  -- CANNOT_ANSWER: <one-line reason>
  ```
- Always include a LIMIT clause (use 100 if unsure).
- For "lowest" / "minimum" / "least" use ORDER BY <col> ASC.
- For "highest" / "maximum" / "top" / "most" use ORDER BY <col> DESC.
- No INSERT, UPDATE, DELETE, DROP, ATTACH, COPY, INSTALL, LOAD,
  PRAGMA, or SET statements. Read-only queries only.
- Identifier casing matches the schema exactly.
"""


FEW_SHOT_EXAMPLES = """Examples (study the shapes — they match the real schema):

Q: Which department has the highest attrition rate?
```sql
SELECT department, attrition_rate
FROM attrition_by_department
ORDER BY attrition_rate DESC
LIMIT 1
```

Q: Which country has the lowest attrition?
```sql
SELECT country, attrition_rate
FROM attrition_by_country
ORDER BY attrition_rate ASC
LIMIT 1
```

Q: Top 5 paying departments?
```sql
SELECT department, avg_salary
FROM salary_by_department
ORDER BY avg_salary DESC
LIMIT 5
```

Q: How many people joined each year?
```sql
SELECT hire_year, SUM(hires) AS hires
FROM workforce_hiring_trends
GROUP BY hire_year
ORDER BY hire_year
LIMIT 100
```
"""


def build_user_prompt(schema_doc: str, question: str) -> str:
    return (
        f"{schema_doc}\n\n"
        f"{FEW_SHOT_EXAMPLES}\n"
        f"Now answer THIS question with a single SQL block:\n"
        f"Q: {question.strip()}\n"
    )


# ── Output extraction ────────────────────────────────────────────────────
_FENCE_RE = re.compile(
    r"```(?:sql)?\s*(?P<sql>.+?)\s*```",
    re.DOTALL | re.IGNORECASE,
)


def extract_sql(model_text: str) -> str:
    """Pull the SQL out of the fenced block. Falls back to the raw text
    if no fence is present (Gemma sometimes forgets the fences).

    With few-shot examples the model returns MULTIPLE fenced blocks
    (the example answers + its own). We want the LAST one -- the one
    that responds to the user's actual question.
    """
    if not model_text:
        return ""
    matches = list(_FENCE_RE.finditer(model_text))
    if matches:
        return matches[-1].group("sql").strip()
    # Fallback -- strip leading prose lines and treat the rest as SQL.
    lines = [ln for ln in model_text.splitlines() if ln.strip()]
    if lines and lines[0].lower().startswith(("here", "the sql", "this query")):
        lines = lines[1:]
    return "\n".join(lines).strip()


def is_cannot_answer(sql: str) -> bool:
    """True only when the model emitted the explicit sentinel.

    Plain English like "I cannot answer this" must NOT match -- that's
    just a refusal we want to treat as an empty SQL response so the
    downstream code path returns a generic error.
    """
    return "CANNOT_ANSWER" in (sql or "")
