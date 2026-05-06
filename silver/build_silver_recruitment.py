"""Silver — recruitment funnel events."""
from __future__ import annotations

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from utils import build_spark, bronze_path, get_logger, silver_path

log = get_logger(__name__)
TABLE = "fct_recruitment"

VALID_STAGES = ["applied", "screen", "interview", "offer", "hired", "rejected"]


def transform(bronze: DataFrame) -> DataFrame:
    return (
        bronze
        .filter(F.col("application_id").isNotNull())
        .dropDuplicates(["application_id", "stage"])
        .filter(F.col("stage").isin(*VALID_STAGES))
        .withColumn("stage_rank",
                    F.expr("CASE stage "
                           "WHEN 'applied'   THEN 1 "
                           "WHEN 'screen'    THEN 2 "
                           "WHEN 'interview' THEN 3 "
                           "WHEN 'offer'     THEN 4 "
                           "WHEN 'hired'     THEN 5 "
                           "WHEN 'rejected'  THEN 6 END"))
    )


def main() -> None:
    spark  = build_spark(app_name="silver-recruitment")
    bronze = spark.read.parquet(bronze_path("recruitment"))
    silver = transform(bronze)
    out    = silver_path(TABLE)
    log.info("writing silver table=%s rows=%d -> %s", TABLE, silver.count(), out)
    silver.write.mode("overwrite").partitionBy("department").parquet(out)


if __name__ == "__main__":
    main()
