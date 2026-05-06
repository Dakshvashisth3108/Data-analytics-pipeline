"""Gold mart — headcount & attrition by department/location/month."""
from __future__ import annotations

from pyspark.sql import functions as F

from utils import build_spark, get_logger, gold_path, silver_path

log = get_logger(__name__)
MART = "gold_headcount"


def main() -> None:
    spark = build_spark(app_name="gold-headcount")
    emp   = spark.read.parquet(silver_path("dim_employee")).filter(F.col("is_current"))

    headcount = (
        emp.groupBy("department", "location")
           .agg(
               F.count("*").alias("headcount"),
               F.sum(F.when(F.col("is_active"), 1).otherwise(0)).alias("active_headcount"),
               F.sum(F.when(F.col("is_active") == False, 1).otherwise(0)).alias("attrition_count"),
               F.round(F.avg("base_salary"), 2).alias("avg_salary"),
               F.round(F.avg("tenure_days") / 365.0, 2).alias("avg_tenure_years"),
           )
           .withColumn("attrition_rate",
                       F.round(F.col("attrition_count") / F.col("headcount"), 4))
           .withColumn("snapshot_date", F.current_date())
    )

    out = gold_path(MART)
    log.info("writing %s rows=%d -> %s", MART, headcount.count(), out)
    headcount.write.mode("overwrite").parquet(out)


if __name__ == "__main__":
    main()
