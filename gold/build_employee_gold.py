"""Gold orchestrator — Silver dim_employee -> business-ready Gold marts.

Reads the cleaned ``data/silver/dim_employee/`` table once, runs every
analytic transformation defined in this package, validates each output,
and writes Parquet to ``data/gold/<domain>/<metric>/``.

Each mart is independent: a failure in one transformation logs the
exception and continues with the next. The job exits with code 8 if any
mart failed -- ready for Airflow / Cron / CI gating.

Run from the project root (Windows PowerShell):

    python -m gold.build_employee_gold                       # build all marts
    python -m gold.build_employee_gold --marts attrition/by_department salary/distribution
    python -m gold.build_employee_gold --mode append         # default is overwrite
    python -m gold.build_employee_gold --fail-on-validation  # strict CI mode
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable

# sys.path bootstrap
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pyspark.sql import DataFrame, SparkSession

from gold import attrition, performance, salary, workforce
from gold.validation import GoldCheck, validate_mart
from utils import (
    build_spark,
    get_logger,
    gold_path,
    load_config,
    silver_path,
)

LOG = get_logger("hcm.gold.employees")
SOURCE_TABLE = "dim_employee"

# ── Mart registry ─────────────────────────────────────────────────────────
# Each tuple: (domain, metric, transform_fn, required_columns)
MartFn = Callable[[DataFrame], DataFrame]
MARTS: list[tuple[str, str, MartFn, list[str]]] = [
    # Attrition Analytics
    ("attrition",   "by_department",      attrition.attrition_by_department,
        ["department", "headcount", "attrited", "active", "attrition_rate"]),
    ("attrition",   "by_country",         attrition.attrition_by_country,
        ["country", "headcount", "attrited", "active", "attrition_rate"]),
    ("attrition",   "trend_by_cohort",    attrition.attrition_trend_by_cohort,
        ["hire_year", "headcount", "attrition_rate"]),
    ("attrition",   "by_tenure_bucket",   attrition.attrition_by_tenure_bucket,
        ["tenure_bucket", "headcount", "attrition_rate"]),

    # Salary Analytics
    ("salary",      "by_department",      salary.salary_by_department,
        ["department", "avg_salary", "median_salary",
         "p25_salary", "p75_salary", "stddev_salary", "total_payroll"]),
    ("salary",      "top_paying_depts",   salary.top_paying_departments,
        ["rank", "department", "avg_salary"]),
    ("salary",      "distribution",       salary.salary_distribution_stats,
        ["avg_salary", "median_salary", "p95_salary", "p99_salary"]),

    # Workforce Analytics
    ("workforce",   "by_country",         workforce.headcount_by_country,
        ["country", "headcount", "active", "attrited"]),
    ("workforce",   "by_department",      workforce.headcount_by_department,
        ["department", "headcount", "active", "attrited"]),
    ("workforce",   "experience_distribution", workforce.experience_distribution,
        ["experience_bucket", "headcount", "share_pct"]),
    ("workforce",   "hiring_trends",      workforce.hiring_trends,
        ["hire_year", "hire_month", "hires"]),

    # Performance Analytics
    ("performance", "by_department",      performance.performance_by_department,
        ["department", "rated_employees", "avg_rating",
         "high_performers", "high_performer_pct"]),
    ("performance", "top_teams",          performance.top_performing_teams,
        ["rank", "department", "avg_rating"]),
    ("performance", "vs_salary",          performance.performance_vs_salary,
        ["performance_rating", "employees", "avg_salary", "median_salary"]),
]


# ── CLI ────────────────────────────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Build Gold business marts from Silver dim_employee.",
    )
    p.add_argument("--mode", choices=["overwrite", "append"], default="overwrite",
                   help="Spark write mode (default overwrite — full snapshot).")
    p.add_argument("--marts", nargs="*", default=None,
                   help='Limit to specific "domain/metric" names. '
                        'Default: all registered marts.')
    p.add_argument("--fail-on-validation", action="store_true",
                   help="Exit non-zero if any mart validation fails.")
    p.add_argument("--coalesce", type=int, default=1,
                   help="Coalesce partitions before write (default 1 — small marts).")
    return p.parse_args()


# ── Per-mart runner ───────────────────────────────────────────────────────
def run_mart(silver: DataFrame, domain: str, metric: str,
             fn: MartFn, required: list[str], *,
             mode: str, coalesce: int) -> GoldCheck:
    name = f"{domain}/{metric}"
    out_path = gold_path(name)
    LOG.info("mart_run name=%s out=%s", name, out_path)

    df = fn(silver)
    df = df.coalesce(max(1, coalesce)) if coalesce else df

    df.cache()
    check = validate_mart(name, df, required_columns=required)
    if check.passed:
        LOG.info("mart_validated name=%s rows=%d cols=%d",
                 name, check.rows, check.columns)
    else:
        LOG.warning("mart_validation_issue name=%s rows=%d detail=%s",
                    name, check.rows, check.detail)

    (df.write.mode(mode).parquet(out_path))
    df.unpersist()
    LOG.info("mart_written name=%s rows=%d", name, check.rows)
    return check


# ── Entrypoint ────────────────────────────────────────────────────────────
def main() -> int:
    args = parse_args()
    cfg = load_config()

    try:
        spark = build_spark(app_name=f"gold-{SOURCE_TABLE}")
    except Exception:
        LOG.exception("spark_init_failed")
        return 2

    src = silver_path(SOURCE_TABLE)
    LOG.info("reading_silver path=%s", src)
    try:
        silver = spark.read.parquet(src).cache()
    except Exception:
        LOG.exception("silver_read_failed path=%s — has the Silver job run?", src)
        return 3

    silver_count = silver.count()
    LOG.info("silver_loaded rows=%d", silver_count)
    if silver_count == 0:
        LOG.warning("silver_empty — no marts to build. Exiting cleanly.")
        return 0

    # Filter mart registry if user asked for a subset
    selected = MARTS
    if args.marts:
        wanted = set(args.marts)
        selected = [m for m in MARTS if f"{m[0]}/{m[1]}" in wanted]
        unmatched = wanted - {f"{m[0]}/{m[1]}" for m in MARTS}
        if unmatched:
            LOG.error("unknown_marts=%s — see registry in build_employee_gold.py",
                      sorted(unmatched))
            return 4
        if not selected:
            LOG.error("no_marts_selected")
            return 4

    LOG.info("running_marts count=%d mode=%s coalesce=%d",
             len(selected), args.mode, args.coalesce)

    results: list[GoldCheck] = []
    failures = 0
    for domain, metric, fn, required in selected:
        try:
            results.append(run_mart(
                silver, domain, metric, fn, required,
                mode=args.mode, coalesce=args.coalesce,
            ))
        except Exception:
            failures += 1
            LOG.exception("mart_failed name=%s/%s", domain, metric)

    silver.unpersist()

    validation_failures = [r for r in results if not r.passed]
    LOG.info("gold_complete marts=%d ok=%d validation_warnings=%d failures=%d",
             len(selected), len(results) - len(validation_failures),
             len(validation_failures), failures)

    if failures:
        return 8
    if args.fail_on_validation and validation_failures:
        return 9
    return 0


if __name__ == "__main__":
    sys.exit(main())
