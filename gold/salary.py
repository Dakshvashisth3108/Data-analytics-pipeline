"""Salary analytics — Gold marts."""
from __future__ import annotations

from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.window import Window

# percentile_approx is exact enough for HR analytics and avoids the
# full-shuffle that an exact percentile would force.
_PCT = lambda c, p: F.round(F.expr(f"percentile_approx({c}, {p})"), 2)


def salary_by_department(silver: DataFrame) -> DataFrame:
    """Salary stats per department: mean, median, IQR, std, payroll."""
    valid = silver.filter(F.col("salary").isNotNull())
    return (
        valid.groupBy("department")
        .agg(
            F.count("*").alias("employees_with_salary"),
            F.round(F.avg("salary"), 2).alias("avg_salary"),
            _PCT("salary", 0.5).alias("median_salary"),
            _PCT("salary", 0.25).alias("p25_salary"),
            _PCT("salary", 0.75).alias("p75_salary"),
            _PCT("salary", 0.90).alias("p90_salary"),
            F.round(F.stddev("salary"), 2).alias("stddev_salary"),
            F.round(F.min("salary"), 2).alias("min_salary"),
            F.round(F.max("salary"), 2).alias("max_salary"),
            F.round(F.sum("salary"), 2).alias("total_payroll"),
        )
        .withColumn("snapshot_date", F.current_date())
        .orderBy(F.desc("avg_salary"))
    )


def top_paying_departments(silver: DataFrame, top_n: int = 5) -> DataFrame:
    """Top-N departments by mean salary, ranked dense."""
    base = salary_by_department(silver)
    w = Window.orderBy(F.desc("avg_salary"))
    return (
        base
        .withColumn("rank", F.dense_rank().over(w))
        .filter(F.col("rank") <= top_n)
        .select("rank", "department", "avg_salary",
                "median_salary", "employees_with_salary",
                "total_payroll", "snapshot_date")
        .orderBy("rank")
    )


def salary_distribution_stats(silver: DataFrame) -> DataFrame:
    """Single-row company-wide salary distribution stats."""
    valid = silver.filter(F.col("salary").isNotNull())
    return (
        valid.agg(
            F.count("*").alias("employees_with_salary"),
            F.round(F.avg("salary"), 2).alias("avg_salary"),
            _PCT("salary", 0.5).alias("median_salary"),
            _PCT("salary", 0.25).alias("p25_salary"),
            _PCT("salary", 0.75).alias("p75_salary"),
            _PCT("salary", 0.90).alias("p90_salary"),
            _PCT("salary", 0.95).alias("p95_salary"),
            _PCT("salary", 0.99).alias("p99_salary"),
            F.round(F.stddev("salary"), 2).alias("stddev_salary"),
            F.round(F.min("salary"), 2).alias("min_salary"),
            F.round(F.max("salary"), 2).alias("max_salary"),
            F.round(F.sum("salary"), 2).alias("total_payroll"),
        )
        .withColumn("snapshot_date", F.current_date())
    )
