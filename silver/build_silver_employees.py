"""Silver layer ETL — Bronze (raw HCM employee parquet) -> Silver (clean dim_employee).

Reads the bronze parquet produced by ``bronze/ingest_employee_stream.py``,
runs the cleaning pipeline defined in ``silver/transformations.py``, runs
data-quality checks defined in ``silver/data_quality.py``, and writes the
result as Parquet under ``data/silver/dim_employee/`` partitioned by the
canonical department.

Run from the project root (Windows PowerShell):

    python -m silver.build_silver_employees                    # full reload
    python -m silver.build_silver_employees --since 2026-05-01 # incremental
    python -m silver.build_silver_employees --fail-on-dq       # strict mode

Design
------
* **Idempotent**: writes with ``mode=overwrite`` (full reload) by default,
  ``--mode append`` if a future incremental flow needs it.
* **Modular**: every cleaning step lives in ``silver/transformations.py``
  as a pure function; this file only orchestrates IO + DQ.
* **DQ-gated**: the job logs every check, and (with ``--fail-on-dq``)
  exits non-zero on any blocking failure -- ready to wire into Airflow.
* **Forward-compatible with Gold**: output is partitioned by
  ``department`` and includes both cleaned + raw columns so Gold marts
  can pivot/aggregate cheaply and audit the lineage.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# sys.path bootstrap so direct invocation also works
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from silver.data_quality import (
    DataQualityError,
    QualityReport,
    run_checks,
)
from silver.transformations import transform_bronze_to_silver
from utils import (
    Config,
    bronze_path,
    build_spark,
    get_logger,
    load_config,
    silver_path,
)

LOG = get_logger("hcm.silver.employees")
SOURCE_STREAM = "employees"
SILVER_TABLE  = "dim_employee"


# ── CLI ───────────────────────────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Bronze HCM employees -> Silver dim_employee")
    p.add_argument("--since", default=None,
                   help="Filter bronze by ingest_date >= this ISO date (e.g. 2026-05-01).")
    p.add_argument("--mode", choices=["overwrite", "append"], default="overwrite",
                   help="Write mode for the Silver Parquet sink.")
    p.add_argument("--fail-on-dq", action="store_true",
                   help="Exit 6 on any blocking data-quality check failure.")
    return p.parse_args()


# ── IO helpers ────────────────────────────────────────────────────────────
def read_bronze(spark: SparkSession, since: str | None) -> DataFrame:
    src = bronze_path(SOURCE_STREAM)
    LOG.info("reading_bronze path=%s since=%s", src, since or "-")
    df = spark.read.parquet(src)
    if since:
        df = df.filter(F.col("ingest_date") >= F.lit(since))
    return df


def write_silver(silver: DataFrame, mode: str) -> str:
    out = silver_path(SILVER_TABLE)
    LOG.info("writing_silver path=%s mode=%s", out, mode)
    (
        silver.write
        .mode(mode)
        .partitionBy("department")
        .parquet(out)
    )
    return out


# ── DQ orchestration ──────────────────────────────────────────────────────
def evaluate_quality(silver: DataFrame, cfg: Config, fail_on_dq: bool) -> QualityReport:
    s_cfg = cfg.get("silver.employees.dq") or {}
    report = run_checks(
        silver,
        max_invalid_salary_pct=float(s_cfg.get("max_invalid_salary_pct", 0.10)),
        max_invalid_date_pct=float(s_cfg.get("max_invalid_date_pct", 0.10)),
        max_unknown_department_pct=float(s_cfg.get("max_unknown_department_pct", 0.05)),
    )
    LOG.info("dq_report rows=%d", report.total_rows)
    for chk in report.checks:
        LOG.info("dq_check name=%s value=%.4f threshold=%.4f passed=%s blocking=%s",
                 chk.name, chk.value, chk.threshold,
                 "yes" if chk.passed else "no",
                 "yes" if chk.blocking else "no")
    blockers = report.blocking_failures
    if blockers and fail_on_dq:
        details = "; ".join(f"{c.name}={c.value:.4f}" for c in blockers)
        raise DataQualityError(f"{len(blockers)} blocking DQ failure(s): {details}")
    return report


# ── Entrypoint ────────────────────────────────────────────────────────────
def main() -> int:
    args = parse_args()
    cfg  = load_config()

    try:
        spark = build_spark(app_name=f"silver-{SILVER_TABLE}")
    except Exception:
        LOG.exception("spark_init_failed")
        return 2

    try:
        bronze = read_bronze(spark, args.since)
    except Exception:
        LOG.exception("bronze_read_failed")
        return 3

    bronze_count = bronze.count()
    LOG.info("bronze_loaded rows=%d", bronze_count)
    if bronze_count == 0:
        LOG.warning("bronze_empty — nothing to clean. Exiting cleanly.")
        return 0

    try:
        silver = transform_bronze_to_silver(bronze)
    except Exception:
        LOG.exception("transformation_failed")
        return 4

    silver = silver.cache()
    silver_count = silver.count()
    LOG.info("silver_built rows=%d (deduped from %d)", silver_count, bronze_count)

    try:
        evaluate_quality(silver, cfg, fail_on_dq=args.fail_on_dq)
    except DataQualityError as exc:
        LOG.error("data_quality_blocked %s", exc)
        return 6
    except Exception:
        LOG.exception("dq_check_failed")
        return 5

    try:
        out = write_silver(silver, args.mode)
    except Exception:
        LOG.exception("silver_write_failed")
        return 7
    finally:
        silver.unpersist()

    LOG.info("silver_complete out=%s rows=%d", out, silver_count)
    return 0


if __name__ == "__main__":
    sys.exit(main())
