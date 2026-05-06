"""Silver — employees (SCD-2 dim_employee).

Reads bronze employee events, deduplicates per (employee_id, event_ts), and
builds a slowly-changing-dimension type-2 table where each row represents a
versioned record of an employee with ``valid_from`` / ``valid_to`` /
``is_current`` columns.
"""
from __future__ import annotations

from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.window import Window

from utils import build_spark, bronze_path, get_logger, silver_path

log = get_logger(__name__)

TABLE = "dim_employee"


def transform(bronze: DataFrame) -> DataFrame:
    base = (
        bronze
        .filter(F.col("employee_id").isNotNull())
        .dropDuplicates(["employee_id", "event_ts"])
        .withColumn("email", F.lower(F.trim(F.col("email"))))
        .withColumn("full_name",
                    F.concat_ws(" ", F.col("first_name"), F.col("last_name")))
        .withColumn("tenure_days",
                    F.datediff(F.current_date(), F.col("hire_date")))
    )

    w = Window.partitionBy("employee_id").orderBy("event_ts")
    scd = (
        base
        .withColumn("valid_from", F.col("event_ts"))
        .withColumn("valid_to",
                    F.lead("event_ts").over(w))
        .withColumn("is_current", F.col("valid_to").isNull())
    )
    return scd


def main() -> None:
    spark  = build_spark(app_name="silver-employees")
    bronze = spark.read.parquet(bronze_path("employees"))
    out    = silver_path(TABLE)

    silver = transform(bronze)
    log.info("writing silver table=%s rows=%d -> %s",
             TABLE, silver.count(), out)
    (silver.write
        .mode("overwrite")
        .partitionBy("department")
        .parquet(out))


if __name__ == "__main__":
    main()
