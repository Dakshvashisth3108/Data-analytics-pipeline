"""Silver — attendance (cleaned daily fact).

Removes duplicates, validates hour ranges, and tags weekend/weekday.
"""
from __future__ import annotations

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from utils import build_spark, bronze_path, get_logger, silver_path

log = get_logger(__name__)

TABLE = "fct_attendance"


def transform(bronze: DataFrame) -> DataFrame:
    return (
        bronze
        .filter(F.col("employee_id").isNotNull() & F.col("work_date").isNotNull())
        .dropDuplicates(["attendance_id"])
        .withColumn("hours_worked",
                    F.when((F.col("hours_worked") < 0) | (F.col("hours_worked") > 24), None)
                     .otherwise(F.col("hours_worked")))
        .withColumn("dow", F.dayofweek("work_date"))
        .withColumn("is_weekend", F.col("dow").isin(1, 7))
        .withColumn("status", F.lower(F.col("status")))
    )


def main() -> None:
    spark  = build_spark(app_name="silver-attendance")
    bronze = spark.read.parquet(bronze_path("attendance"))
    silver = transform(bronze)
    out    = silver_path(TABLE)
    log.info("writing silver table=%s rows=%d -> %s", TABLE, silver.count(), out)
    (silver.write
        .mode("overwrite")
        .partitionBy("work_date")
        .parquet(out))


if __name__ == "__main__":
    main()
