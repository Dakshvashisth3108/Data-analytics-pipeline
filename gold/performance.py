"""Performance analytics — Gold marts."""
from __future__ import annotations

from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.window import Window


def performance_by_department(silver: DataFrame) -> DataFrame:
    """Avg rating + high/low performer mix per department."""
    valid = silver.filter(F.col("performance_rating").isNotNull())
    return (
        valid.groupBy("department")
        .agg(
            F.count("*").alias("rated_employees"),
            F.round(F.avg("performance_rating"), 2).alias("avg_rating"),
            F.sum(F.when(F.col("performance_rating") >= 4, 1).otherwise(0)).alias("high_performers"),
            F.sum(F.when(F.col("performance_rating") <= 2, 1).otherwise(0)).alias("low_performers"),
        )
        .withColumn("high_performer_pct",
                    F.round(F.col("high_performers") / F.col("rated_employees"), 4))
        .withColumn("low_performer_pct",
                    F.round(F.col("low_performers")  / F.col("rated_employees"), 4))
        .withColumn("snapshot_date", F.current_date())
        .orderBy(F.desc("avg_rating"))
    )


def top_performing_teams(silver: DataFrame, *,
                         min_team_size: int = 5, top_n: int = 5) -> DataFrame:
    """Top departments by avg rating, with a min_team_size guard so a
    team of 2 doesn't game the leaderboard."""
    base = performance_by_department(silver).filter(
        F.col("rated_employees") >= min_team_size
    )
    w = Window.orderBy(F.desc("avg_rating"))
    return (
        base
        .withColumn("rank", F.dense_rank().over(w))
        .filter(F.col("rank") <= top_n)
        .select("rank", "department", "avg_rating",
                "rated_employees", "high_performer_pct",
                "snapshot_date")
        .orderBy("rank")
    )


def performance_vs_salary(silver: DataFrame) -> DataFrame:
    """Salary distribution per performance rating."""
    valid = silver.filter(
        F.col("performance_rating").isNotNull()
        & F.col("salary").isNotNull()
    )
    return (
        valid.groupBy("performance_rating")
        .agg(
            F.count("*").alias("employees"),
            F.round(F.avg("salary"), 2).alias("avg_salary"),
            F.round(F.expr("percentile_approx(salary, 0.5)"), 2).alias("median_salary"),
            F.round(F.min("salary"), 2).alias("min_salary"),
            F.round(F.max("salary"), 2).alias("max_salary"),
        )
        .withColumn("snapshot_date", F.current_date())
        .orderBy("performance_rating")
    )
