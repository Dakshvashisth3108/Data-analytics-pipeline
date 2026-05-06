"""Silver — performance reviews."""
from __future__ import annotations

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from utils import build_spark, bronze_path, get_logger, silver_path

log = get_logger(__name__)
TABLE = "fct_performance"


def transform(bronze: DataFrame) -> DataFrame:
    return (
        bronze
        .filter(F.col("employee_id").isNotNull() & F.col("rating").between(1, 5))
        .dropDuplicates(["review_id"])
        .withColumn("goals_met_pct",
                    F.when(F.col("goals_met_pct") < 0, 0)
                     .otherwise(F.col("goals_met_pct")))
        .withColumn("is_high_performer", F.col("rating") >= 4)
    )


def main() -> None:
    spark  = build_spark(app_name="silver-performance")
    bronze = spark.read.parquet(bronze_path("performance"))
    silver = transform(bronze)
    out    = silver_path(TABLE)
    log.info("writing silver table=%s rows=%d -> %s", TABLE, silver.count(), out)
    silver.write.mode("overwrite").partitionBy("cycle").parquet(out)


if __name__ == "__main__":
    main()
