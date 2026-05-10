"""Natural-language -> SQL engine for HCM Gold marts.

Pipeline:
    user question
        -> SchemaCatalog (parquet -> table description)
        -> Prompt builder (schema + question)
        -> Ollama (Gemma 2B by default) -> SQL string
        -> sqlglot validator (allowlist + safety)
        -> DuckDB (read-only views over Gold parquet) -> rows
        -> AnswerResult (structured)
"""
from .engine import AnswerResult, NL2SQLEngine
from .ollama_client import OllamaClient, OllamaUnavailable
from .schema_introspect import SchemaCatalog, TableSchema
from .sql_validator import UnsafeSQLError, validate_sql
from .duckdb_runner import DuckDBRunner

__all__ = [
    "AnswerResult",
    "NL2SQLEngine",
    "OllamaClient",
    "OllamaUnavailable",
    "SchemaCatalog",
    "TableSchema",
    "UnsafeSQLError",
    "validate_sql",
    "DuckDBRunner",
]
