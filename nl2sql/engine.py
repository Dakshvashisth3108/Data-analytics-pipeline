"""End-to-end NL -> SQL -> rows orchestrator.

Lifecycle:
    1. Build SchemaCatalog from data/gold/.
    2. Lazily build SQL via Ollama (Gemma 2B) using a schema-aware prompt.
    3. Validate the model's SQL with sqlglot (allowlist + safety).
    4. Execute on DuckDB views over Gold parquet.
    5. Return a structured ``AnswerResult``.

The engine is the only piece other modules should need to instantiate.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from utils import Config, get_logger, load_config

from .duckdb_runner import DuckDBRunner, QueryResult
from .ollama_client import OllamaClient, OllamaUnavailable
from .prompts import (
    SYSTEM_PROMPT, build_user_prompt, extract_sql, is_cannot_answer,
)
from .schema_introspect import SchemaCatalog, build_catalog
from .sql_validator import UnsafeSQLError, validate_sql

LOG = get_logger("hcm.nl2sql.engine")


@dataclass
class AnswerResult:
    question: str
    sql: str | None
    columns: list[str] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    row_count: int = 0
    referenced_tables: list[str] = field(default_factory=list)
    elapsed_ms_llm: int = 0
    elapsed_ms_sql: int = 0
    cannot_answer: bool = False
    error: str | None = None
    raw_model_output: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class NL2SQLEngine:
    def __init__(self, cfg: Config | None = None,
                 catalog: SchemaCatalog | None = None,
                 ollama: OllamaClient | None = None,
                 duck: DuckDBRunner | None = None) -> None:
        self.cfg = cfg or load_config()
        self.catalog = catalog or build_catalog(
            self.cfg.get("nl2sql.duckdb.gold_root", "data/gold")
        )
        if not self.catalog.tables:
            raise RuntimeError(
                "No Gold marts found. Run `python -m gold.gold_etl` first."
            )

        ocfg = self.cfg.get("nl2sql.ollama") or {}
        self.ollama = ollama or OllamaClient(
            base_url=str(ocfg.get("base_url", "http://localhost:11434")),
            model=str(ocfg.get("model", "gemma2:2b")),
            timeout_seconds=int(ocfg.get("timeout_seconds", 120)),
            temperature=float(ocfg.get("temperature", 0.1)),
            num_predict=int(ocfg.get("num_predict", 512)),
        )

        dcfg = self.cfg.get("nl2sql.duckdb") or {}
        self.duck = duck or DuckDBRunner(
            self.catalog,
            max_result_rows=int(dcfg.get("max_result_rows", 10_000)),
        )
        self.default_row_limit = int(dcfg.get("default_row_limit", 500))

        scfg = self.cfg.get("nl2sql.safety") or {}
        self.blocked_keywords = tuple(
            (kw or "").upper() for kw in (scfg.get("blocked_keywords") or [])
        ) or None
        self.allowed_kinds = tuple(scfg.get("allowed_statement_kinds") or [])
        self.max_sql_len = int(scfg.get("max_sql_length_chars", 4000))

    # ── public API ───────────────────────────────────────────────────────
    def ask(self, question: str) -> AnswerResult:
        result = AnswerResult(question=question, sql=None)

        # 1. Build the schema-aware prompt
        schema_doc = self.catalog.to_prompt_doc()
        user_prompt = build_user_prompt(schema_doc, question)

        # 2. Ask the LLM for SQL
        try:
            gen = self.ollama.generate(user_prompt, system=SYSTEM_PROMPT)
        except OllamaUnavailable as exc:
            result.error = str(exc)
            return result
        result.raw_model_output = gen.text
        result.elapsed_ms_llm = gen.elapsed_ms
        sql = extract_sql(gen.text)

        if not sql:
            result.error = "model returned empty output"
            return result
        if is_cannot_answer(sql):
            result.cannot_answer = True
            result.sql = sql
            return result

        # 3. Validate
        try:
            kwargs: dict[str, Any] = {
                "allowed_tables": set(self.catalog.view_names()),
                "default_row_limit": self.default_row_limit,
                "max_sql_length_chars": self.max_sql_len,
            }
            if self.blocked_keywords:
                kwargs["blocked_keywords"] = self.blocked_keywords
            if self.allowed_kinds:
                kwargs["allowed_statement_kinds"] = tuple(self.allowed_kinds)
            v = validate_sql(sql, **kwargs)
        except UnsafeSQLError as exc:
            LOG.warning("rejected_sql reason=%s sql=%s", exc, sql[:200])
            result.sql = sql
            result.error = f"unsafe SQL rejected: {exc}"
            return result
        except Exception as exc:  # parsing failures
            LOG.exception("sql_parse_failed")
            result.sql = sql
            result.error = f"could not parse SQL: {exc}"
            return result

        result.sql = v.sql
        result.referenced_tables = v.referenced_tables

        # 4. Execute
        try:
            qr: QueryResult = self.duck.execute(v.sql)
        except Exception as exc:
            LOG.exception("execute_failed")
            result.error = f"DuckDB execution failed: {exc}"
            return result

        result.columns = qr.columns
        result.rows = qr.rows
        result.row_count = qr.row_count
        result.elapsed_ms_sql = qr.elapsed_ms
        return result

    def close(self) -> None:
        self.duck.close()
