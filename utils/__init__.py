"""Shared utilities — config, logging, lakehouse paths, and Spark.

Imports are kept lazy so light-weight callers (the Kafka producer, the
Streamlit dashboard, tests) don't pay the PySpark / JVM startup cost
just to read a config or grab a logger.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .config import Config, load_config
from .logger import get_logger
from .io import bronze_path, silver_path, gold_path, checkpoint_path

if TYPE_CHECKING:
    from .spark import build_spark  # noqa: F401

__all__ = [
    "Config",
    "load_config",
    "get_logger",
    "bronze_path",
    "silver_path",
    "gold_path",
    "checkpoint_path",
    "build_spark",
]


def __getattr__(name: str) -> Any:
    """Lazy-load Spark on first access — avoids JVM boot for Kafka-only jobs."""
    if name == "build_spark":
        from .spark import build_spark
        return build_spark
    raise AttributeError(f"module 'utils' has no attribute {name!r}")
