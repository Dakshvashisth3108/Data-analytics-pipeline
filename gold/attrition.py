"""Attrition analytics — Gold marts.

Each function takes the Silver ``dim_employee`` DataFrame and returns a
business-ready aggregation. Pure DataFrame -> DataFrame so it's testable
in isolation and replayable across snapshots.
"""
from __future__ import annotations

from pyspark.sql import DataFrame
from pyspark.sql import functions as F


def _attrition_aggregates() -> list:
    """Common aggregation columns reused across attrition marts."""
    return [
        F.count("*").alias("headcount"),
        F.sum(F.when(F.col("attrition") == "Yes", 1).otherwise(0)).alias("attrited"),
        F.sum(F.when(F.col("attrition") == "No",  1).otherwise(0)).alias("active"),
    ]


def attrition_by_department(silver: DataFrame) -> DataFrame:
    """Attrition rate per canonical department, sorted worst-first."""
    return (
        silver
        .filter(F.col("department").isNotNull())
        .groupBy("department")
        .agg(*_attrition_aggregates())
        .withColumn("attrition_rate",
                    F.round(F.col("attrited") / F.col("headcount"), 4))
        .withColumn("snapshot_date", F.current_date())
        .orderBy(F.desc("attrition_rate"))
    )


def attrition_by_country(silver: DataFrame) -> DataFrame:
    """Attrition rate per country."""
    return (
        silver
        .filter(F.col("country").isNotNull())
        .groupBy("country")
        .agg(*_attrition_aggregates())
        .withColumn("attrition_rate",
                    F.round(F.col("attrited") / F.col("headcount"), 4))
        .withColumn("snapshot_date", F.current_date())
        .orderBy(F.desc("attrition_rate"))
    )


def attrition_trend_by_cohort(silver: DataFrame) -> DataFrame:
    """Attrition rate by hire-year cohort.

    Useful to spot which joining cohorts churn most — a leading
    indicator of recruiter / onboarding issues.
    """
    return (
        silver
        .filter(F.col("joining_date").isNotNull())
        .withColumn("hire_year", F.year("joining_date"))
        .groupBy("hire_year")
        .agg(*_attrition_aggregates())
        .withColumn("attrition_rate",
                    F.round(F.col("attrited") / F.col("headcount"), 4))
        .withColumn("snapshot_date", F.current_date())
        .orderBy("hire_year")
    )


def attrition_by_tenure_bucket(silver: DataFrame) -> DataFrame:
    """Attrition by tenure bucket (years from joining_date to today)."""
    tenure_years = F.months_between(F.current_date(), F.col("joining_date")) / 12
    bucket = (
        F.when(tenure_years < 1,  "0-1y")
         .when(tenure_years < 3,  "1-3y")
         .when(tenure_years < 5,  "3-5y")
         .when(tenure_years < 10, "5-10y")
         .otherwise("10y+")
    )
    return (
        silver
        .filter(F.col("joining_date").isNotNull())
        .withColumn("tenure_bucket", bucket)
        .groupBy("tenure_bucket")
        .agg(*_attrition_aggregates())
        .withColumn("attrition_rate",
                    F.round(F.col("attrited") / F.col("headcount"), 4))
        .withColumn("snapshot_date", F.current_date())
    )
