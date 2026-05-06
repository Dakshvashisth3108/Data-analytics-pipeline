"""Workforce analytics — Gold marts."""
from __future__ import annotations

from pyspark.sql import DataFrame
from pyspark.sql import functions as F


def headcount_by_country(silver: DataFrame) -> DataFrame:
    """Headcount + active/attrited split per country."""
    return (
        silver
        .filter(F.col("country").isNotNull())
        .groupBy("country")
        .agg(
            F.count("*").alias("headcount"),
            F.sum(F.when(F.col("attrition") == "No",  1).otherwise(0)).alias("active"),
            F.sum(F.when(F.col("attrition") == "Yes", 1).otherwise(0)).alias("attrited"),
        )
        .withColumn("active_pct",
                    F.round(F.col("active") / F.col("headcount"), 4))
        .withColumn("snapshot_date", F.current_date())
        .orderBy(F.desc("headcount"))
    )


def headcount_by_department(silver: DataFrame) -> DataFrame:
    """Headcount + active/attrited split per department."""
    return (
        silver
        .filter(F.col("department").isNotNull())
        .groupBy("department")
        .agg(
            F.count("*").alias("headcount"),
            F.sum(F.when(F.col("attrition") == "No",  1).otherwise(0)).alias("active"),
            F.sum(F.when(F.col("attrition") == "Yes", 1).otherwise(0)).alias("attrited"),
        )
        .withColumn("active_pct",
                    F.round(F.col("active") / F.col("headcount"), 4))
        .withColumn("snapshot_date", F.current_date())
        .orderBy(F.desc("headcount"))
    )


def experience_distribution(silver: DataFrame) -> DataFrame:
    """Headcount per experience bucket — useful for seniority pyramids."""
    bucket = (
        F.when(F.col("experience_years") < 2,  "0-2y")
         .when(F.col("experience_years") < 5,  "2-5y")
         .when(F.col("experience_years") < 10, "5-10y")
         .when(F.col("experience_years") < 20, "10-20y")
         .otherwise("20y+")
    )
    bucket_order = (
        F.when(F.col("experience_bucket") == "0-2y",   1)
         .when(F.col("experience_bucket") == "2-5y",   2)
         .when(F.col("experience_bucket") == "5-10y",  3)
         .when(F.col("experience_bucket") == "10-20y", 4)
         .otherwise(5)
    )
    base = (
        silver
        .filter(F.col("experience_years").isNotNull())
        .withColumn("experience_bucket", bucket)
    )
    total = base.count() or 1  # avoid div-by-zero
    return (
        base
        .groupBy("experience_bucket")
        .agg(F.count("*").alias("headcount"))
        .withColumn("share_pct",
                    F.round(F.col("headcount") / F.lit(total), 4))
        .withColumn("_order", bucket_order)
        .orderBy("_order").drop("_order")
        .withColumn("snapshot_date", F.current_date())
    )


def hiring_trends(silver: DataFrame) -> DataFrame:
    """Monthly hires (year-month) based on joining_date."""
    return (
        silver
        .filter(F.col("joining_date").isNotNull())
        .withColumn("hire_year",  F.year("joining_date"))
        .withColumn("hire_month", F.month("joining_date"))
        .groupBy("hire_year", "hire_month")
        .agg(F.count("*").alias("hires"))
        .withColumn("year_month",
                    F.format_string("%04d-%02d",
                                    F.col("hire_year"), F.col("hire_month")))
        .withColumn("snapshot_date", F.current_date())
        .orderBy("hire_year", "hire_month")
    )
