"""Data-quality checks for the Silver employee table.

Each check runs a single Spark aggregation and returns a structured dict.
The orchestrator collects them and:

* logs a summary line for every check,
* compares each ratio to a configurable threshold,
* raises ``DataQualityError`` if any **blocking** check fails.

Keeping checks declarative (a list of dicts) makes it trivial for Gold
layer jobs to reuse the same primitives, and for Airflow/MWAA tasks to
publish the metrics to Datadog/CloudWatch later.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pyspark.sql import DataFrame
from pyspark.sql import functions as F


class DataQualityError(RuntimeError):
    """Raised when a blocking DQ check fails."""


@dataclass
class CheckResult:
    name: str
    value: float
    threshold: float
    passed: bool
    blocking: bool
    detail: str = ""


@dataclass
class QualityReport:
    total_rows: int
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def failures(self) -> list[CheckResult]:
        return [c for c in self.checks if not c.passed]

    @property
    def blocking_failures(self) -> list[CheckResult]:
        return [c for c in self.failures if c.blocking]

    def to_log_dict(self) -> dict[str, float | int | str]:
        flat: dict[str, float | int | str] = {"total_rows": self.total_rows}
        for c in self.checks:
            flat[f"{c.name}.value"] = round(c.value, 4)
            flat[f"{c.name}.passed"] = "yes" if c.passed else "NO"
        return flat


# ── Individual check helpers ──────────────────────────────────────────────
def _ratio(df: DataFrame, predicate) -> float:
    """Fraction of rows satisfying `predicate`. Empty-frame safe."""
    total = df.count()
    if total == 0:
        return 0.0
    matched = df.filter(predicate).count()
    return matched / total


# ── Public API ────────────────────────────────────────────────────────────
def run_checks(silver: DataFrame, *,
               max_invalid_salary_pct: float = 0.10,
               max_invalid_date_pct: float = 0.10,
               max_unknown_department_pct: float = 0.05,
               require_unique_employee_id: bool = True) -> QualityReport:
    """Run the standard DQ suite against the Silver employee table."""
    silver = silver.cache()  # avoid recomputing the lineage on every check
    total = silver.count()
    report = QualityReport(total_rows=total)

    # 1. Employee_id present & unique
    null_id_pct = _ratio(silver, F.col("employee_id").isNull())
    report.checks.append(CheckResult(
        name="null_employee_id_pct",
        value=null_id_pct, threshold=0.0,
        passed=null_id_pct == 0.0, blocking=True,
        detail="No row may have a null employee_id after dedupe.",
    ))

    if require_unique_employee_id and total > 0:
        distinct = silver.select("employee_id").distinct().count()
        dup_ratio = 1 - (distinct / total)
        report.checks.append(CheckResult(
            name="duplicate_employee_id_ratio",
            value=dup_ratio, threshold=0.0,
            passed=dup_ratio == 0.0, blocking=True,
            detail=f"{total - distinct:,} duplicate IDs",
        ))

    # 2. Salary parse-failure rate
    if "salary_valid" in silver.columns and total > 0:
        invalid_salary = _ratio(silver, ~F.col("salary_valid"))
        report.checks.append(CheckResult(
            name="invalid_salary_pct",
            value=invalid_salary, threshold=max_invalid_salary_pct,
            passed=invalid_salary <= max_invalid_salary_pct, blocking=False,
        ))

    # 3. Joining-date parse-failure rate
    if "joining_date_valid" in silver.columns and total > 0:
        invalid_date = _ratio(silver, ~F.col("joining_date_valid"))
        report.checks.append(CheckResult(
            name="invalid_joining_date_pct",
            value=invalid_date, threshold=max_invalid_date_pct,
            passed=invalid_date <= max_invalid_date_pct, blocking=False,
        ))

    # 4. Department canonicalisation rate
    if "department_canonical" in silver.columns and total > 0:
        unknown_dept = _ratio(silver, ~F.col("department_canonical"))
        report.checks.append(CheckResult(
            name="unknown_department_pct",
            value=unknown_dept, threshold=max_unknown_department_pct,
            passed=unknown_dept <= max_unknown_department_pct, blocking=False,
        ))

    silver.unpersist()
    return report
