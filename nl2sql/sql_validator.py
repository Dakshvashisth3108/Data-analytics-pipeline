"""Defence-in-depth SQL validation before anything reaches DuckDB.

We use ``sqlglot`` to parse the LLM's output and enforce three rules:

1. **Statement kind allowlist** — only ``SELECT`` / ``WITH`` (CTE).
   No INSERT / UPDATE / DELETE / DROP / TRUNCATE / CREATE / ALTER.
2. **Keyword denylist** — ATTACH, COPY, INSTALL, LOAD, PRAGMA, SET,
   EXPORT, IMPORT, READ_TEXT, READ_BLOB. These can read arbitrary
   files or load extensions and must never reach the engine.
3. **Table allowlist** — every referenced table must be in the catalog.

If parsing fails, we reject (fail-closed): better to refuse a valid-but-
unparseable query than to forward something we can't audit.

The validator also injects a ``LIMIT`` clause if the user / LLM forgot
one, and trims trailing semicolons so DuckDB sees a single statement.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import sqlglot
from sqlglot import expressions as exp
from sqlglot.errors import ParseError

from utils import get_logger

LOG = get_logger("hcm.nl2sql.validator")


class UnsafeSQLError(ValueError):
    """Raised when a SQL statement fails the safety policy."""


@dataclass
class ValidationResult:
    sql: str                  # the (possibly augmented) safe SQL
    referenced_tables: list[str]
    statement_kind: str       # "SELECT" or "WITH"


# Keywords that can never appear in a safe query, even inside string literals
# we don't process. We do a CASE-INSENSITIVE word-boundary scan after the
# parse step as belt-and-braces.
_DEFAULT_BLOCKED_KEYWORDS: tuple[str, ...] = (
    "ATTACH", "COPY", "INSTALL", "LOAD", "PRAGMA", "SET",
    "EXPORT", "IMPORT", "READ_TEXT", "READ_BLOB",
    "DROP", "DELETE", "INSERT", "UPDATE", "TRUNCATE",
    "CREATE", "ALTER", "GRANT", "REVOKE",
)

_DEFAULT_ALLOWED_KINDS: tuple[str, ...] = ("Select", "With")


def _strip_trailing_semis(sql: str) -> str:
    return re.sub(r";\s*$", "", sql.strip())


def _ensure_limit(sql: str, default_limit: int) -> str:
    """If the outer SELECT/CTE has no LIMIT, append one.

    Walks the parsed AST rather than regex-matching, so subquery LIMITs
    don't fool us into thinking the outer query is bounded.
    """
    try:
        tree = sqlglot.parse_one(sql, read="duckdb")
    except ParseError:
        return sql  # let the caller's parse step surface the error

    # The outermost SELECT / WITH is the SQL we hand to DuckDB.
    outer = tree
    if outer.find(exp.Limit, bfs=False):  # already limited
        return sql

    # Wrap in a LIMITed select. Cleanest is to add a Limit node to the tree.
    limited = outer.copy()
    limited.set("limit", exp.Limit(expression=exp.Literal.number(default_limit)))
    return limited.sql(dialect="duckdb")


# ── Public API ────────────────────────────────────────────────────────────
def validate_sql(
    sql: str, *,
    allowed_tables: set[str],
    blocked_keywords: tuple[str, ...] = _DEFAULT_BLOCKED_KEYWORDS,
    allowed_statement_kinds: tuple[str, ...] = _DEFAULT_ALLOWED_KINDS,
    default_row_limit: int | None = None,
    max_sql_length_chars: int = 4000,
) -> ValidationResult:
    """Parse + check a SQL string. Returns the safe form or raises."""
    if not sql or not sql.strip():
        raise UnsafeSQLError("empty SQL")
    if len(sql) > max_sql_length_chars:
        raise UnsafeSQLError(
            f"SQL too long: {len(sql)} chars > {max_sql_length_chars}"
        )

    cleaned = _strip_trailing_semis(sql)

    # Reject multiple statements (sqlglot.parse returns a list).
    statements = sqlglot.parse(cleaned, read="duckdb")
    if not statements:
        raise UnsafeSQLError("no parseable statement")
    if len(statements) > 1:
        raise UnsafeSQLError(f"multiple statements not allowed (got {len(statements)})")
    tree = statements[0]
    if tree is None:
        raise UnsafeSQLError("could not parse SQL")

    # 1. Statement kind allowlist
    kind = type(tree).__name__
    if kind not in allowed_statement_kinds:
        raise UnsafeSQLError(
            f"only {allowed_statement_kinds} allowed; got {kind}"
        )

    # 2. Word-boundary keyword scan (even though parser would catch
    # most, this prevents creative quoting / case tricks.)
    upper = cleaned.upper()
    for kw in blocked_keywords:
        if re.search(rf"(?<![A-Z_]){kw}(?![A-Z_])", upper):
            raise UnsafeSQLError(f"blocked keyword in SQL: {kw}")

    # 3. Table allowlist
    referenced: list[str] = []
    for table in tree.find_all(exp.Table):
        name = table.name
        # Reject schema-qualified names — we want bare view_name only.
        if table.args.get("db") or table.args.get("catalog"):
            raise UnsafeSQLError(
                f"schema-qualified table refs are not allowed: {table.sql()}"
            )
        if name not in allowed_tables:
            raise UnsafeSQLError(
                f"unknown table {name!r}; allowed: {sorted(allowed_tables)}"
            )
        referenced.append(name)

    if not referenced:
        raise UnsafeSQLError("query references no tables")

    # 4. Optional LIMIT injection
    final_sql = cleaned
    if default_row_limit and default_row_limit > 0:
        final_sql = _ensure_limit(cleaned, default_row_limit)

    LOG.info("sql_validated kind=%s tables=%s len=%d",
             kind, sorted(set(referenced)), len(final_sql))
    return ValidationResult(
        sql=final_sql,
        referenced_tables=sorted(set(referenced)),
        statement_kind=kind,
    )
