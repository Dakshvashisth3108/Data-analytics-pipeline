"""Execute validated SQL against Gold parquet via DuckDB.

DuckDB is started **read-only** (in-memory, ``access_mode='READ_ONLY'``
isn't possible on `:memory:` — but with no ATTACH / no file mutations
the JIT VM can't write anything anyway). We register one VIEW per Gold
mart up front so the LLM only ever sees a curated set of tables —
never the raw filesystem.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import duckdb

from utils import get_logger

from .schema_introspect import SchemaCatalog

LOG = get_logger("hcm.nl2sql.duckdb")


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    elapsed_ms: int


class DuckDBRunner:
    """One DuckDB connection with all Gold marts mounted as views."""

    def __init__(self, catalog: SchemaCatalog,
                 max_result_rows: int = 10_000) -> None:
        self.catalog = catalog
        self.max_result_rows = int(max_result_rows)
        self._conn: duckdb.DuckDBPyConnection | None = None

    def _ensure_open(self) -> duckdb.DuckDBPyConnection:
        if self._conn is not None:
            return self._conn
        self._conn = duckdb.connect(database=":memory:")
        # Defensive: disable any extension auto-install/load for this session.
        try:
            self._conn.execute("SET autoinstall_known_extensions = false;")
            self._conn.execute("SET autoload_known_extensions = false;")
        except duckdb.Error:
            pass

        # Register one VIEW per mart. read_parquet handles globs natively.
        # DuckDB doesn't accept prepared parameters in CREATE VIEW, so we
        # inline the path. Safe because:
        #   * view_name = snake_case from filesystem names (no spec chars)
        #   * parquet_glob is built from gold_path() — internal config, not
        #     user input — but we still escape single quotes defensively.
        for t in self.catalog.tables:
            escaped_path = t.parquet_glob.replace("'", "''")
            try:
                self._conn.execute(
                    f"CREATE OR REPLACE VIEW {t.view_name} AS "
                    f"SELECT * FROM read_parquet('{escaped_path}');"
                )
                LOG.info("view_registered name=%s glob=%s",
                         t.view_name, t.parquet_glob)
            except duckdb.Error:
                LOG.exception("view_register_failed name=%s", t.view_name)
        return self._conn

    def list_views(self) -> list[str]:
        """List only the user-defined views we created (skip system views)."""
        conn = self._ensure_open()
        return [r[0] for r in conn.execute(
            "SELECT view_name FROM duckdb_views() "
            "WHERE schema_name='main' AND internal=false "
            "ORDER BY 1;"
        ).fetchall()]

    def execute(self, sql: str) -> QueryResult:
        conn = self._ensure_open()
        started = time.perf_counter()
        try:
            cursor = conn.execute(sql)
        except duckdb.Error:
            LOG.exception("duckdb_execute_failed sql=%s", sql[:200])
            raise

        cols = [d[0] for d in cursor.description] if cursor.description else []
        # Hard cap: pull at most max_result_rows even if SQL forgot LIMIT
        raw = cursor.fetchmany(self.max_result_rows)
        rows = [dict(zip(cols, r)) for r in raw]
        elapsed = int((time.perf_counter() - started) * 1000)
        LOG.info("duckdb_executed rows=%d elapsed_ms=%d", len(rows), elapsed)
        return QueryResult(
            columns=cols, rows=rows,
            row_count=len(rows), elapsed_ms=elapsed,
        )

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:  # pragma: no cover
                pass
            self._conn = None
