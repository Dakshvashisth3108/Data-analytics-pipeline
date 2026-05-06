"""Gold mart — performance distribution by department & cycle."""
from __future__ import annotations

from pyspark.sql import functions as F

from utils import build_spark, get_logger, gold_path, silver_path

log = get_logger(__name__)
MART = "gold_performance"


def main() -> None:
    spark = build_spark(app_name="gold-performance")

    perf = spark.read.parquet(silver_path("fct_performance"))
    emp  = (spark.read.parquet(silver_path("dim_employee"))
                  .filter(F.col("is_current"))
                  .select("employee_id", "department", "grade"))

    joined = perf.join(emp, on="employee_id", how="left")

    agg = (
        joined.groupBy("department", "cycle")
              .agg(
                  F.count("*").alias("reviews"),
                  F.round(F.avg("rating"), 2).alias("avg_rating"),
                  F.sum(F.when(F.col("is_high_performer"), 1).otherwise(0)).alias("high_performers"),
                  F.sum(F.when(F.col("promotion_flag"), 1).otherwise(0)).alias("promotions"),
                  F.round(F.avg("goals_met_pct"), 2).alias("avg_goals_met_pct"),
                  F.round(F.sum("bonus_amount"), 2).alias("total_bonus"),
              )
              .withColumn("hp_share",
                          F.round(F.col("high_performers") / F.col("reviews"), 4))
              .withColumn("snapshot_date", F.current_date())
    )

    out = gold_path(MART)
    log.info("writing %s rows=%d -> %s", MART, agg.count(), out)
    agg.write.mode("overwrite").parquet(out)


if __name__ == "__main__":
    main()
