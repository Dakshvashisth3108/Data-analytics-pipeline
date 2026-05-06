"""Gold mart — attendance compliance per employee & department."""
from __future__ import annotations

from pyspark.sql import functions as F

from utils import build_spark, get_logger, gold_path, silver_path

log = get_logger(__name__)
MART = "gold_attendance_compliance"


def main() -> None:
    spark = build_spark(app_name="gold-attendance")

    att = spark.read.parquet(silver_path("fct_attendance"))
    emp = (spark.read.parquet(silver_path("dim_employee"))
                  .filter(F.col("is_current"))
                  .select("employee_id", "department", "location"))

    joined = att.join(emp, on="employee_id", how="left")

    agg = (
        joined.groupBy("department", "location")
              .agg(
                  F.count("*").alias("total_records"),
                  F.sum(F.when(F.col("status") == "present", 1).otherwise(0)).alias("present_days"),
                  F.sum(F.when(F.col("status") == "absent",  1).otherwise(0)).alias("absent_days"),
                  F.sum(F.when(F.col("status") == "leave",   1).otherwise(0)).alias("leave_days"),
                  F.sum(F.when(F.col("status") == "wfh",     1).otherwise(0)).alias("wfh_days"),
                  F.sum(F.when(F.col("is_late") == True, 1).otherwise(0)).alias("late_count"),
                  F.round(F.avg("hours_worked"), 2).alias("avg_hours_worked"),
              )
              .withColumn("attendance_rate",
                          F.round(F.col("present_days") / F.col("total_records"), 4))
              .withColumn("snapshot_date", F.current_date())
    )

    out = gold_path(MART)
    log.info("writing %s rows=%d -> %s", MART, agg.count(), out)
    agg.write.mode("overwrite").parquet(out)


if __name__ == "__main__":
    main()
