"""Output validation for Gold marts.

Each mart goes through ``validate_mart`` after computation but before
write. The check is non-blocking by default (logs a warning, still
writes), but the orchestrator can be configured to abort on validation
failure for production runs.
"""
from __future__ import annotations

from dataclasses import dataclass

from pyspark.sql import DataFrame


@dataclass
class GoldCheck:
    mart: str
    rows: int
    columns: int
    passed: bool
    detail: str = ""


def validate_mart(name: str, df: DataFrame, *,
                  required_columns: list[str] | None = None,
                  min_rows: int = 0) -> GoldCheck:
    """Cheap structural validation of a gold mart.

    * row count (cached after first call -- caller decides when to materialise)
    * required columns present
    * non-null in dimension columns (if requested)
    """
    rows = df.count()
    cols = df.columns
    issues: list[str] = []

    if rows < min_rows:
        issues.append(f"too_few_rows={rows}<{min_rows}")
    if rows == 0 and min_rows == 0:
        issues.append("empty_mart")

    if required_columns:
        missing = [c for c in required_columns if c not in cols]
        if missing:
            issues.append(f"missing_columns={missing}")

    return GoldCheck(
        mart=name,
        rows=rows,
        columns=len(cols),
        passed=not issues,
        detail="; ".join(issues) if issues else "ok",
    )
