"""Gold mart — recruitment funnel & source-of-hire."""
from __future__ import annotations

from pyspark.sql import functions as F

from utils import build_spark, get_logger, gold_path, silver_path

log = get_logger(__name__)
MART = "gold_recruitment_funnel"


def main() -> None:
    spark = build_spark(app_name="gold-recruitment")
    rec   = spark.read.parquet(silver_path("fct_recruitment"))

    funnel = (
        rec.groupBy("department", "source", "stage")
           .agg(
               F.countDistinct("application_id").alias("applications"),
               F.round(F.avg("offer_amount"), 2).alias("avg_offer"),
           )
    )

    pivoted = (
        funnel.groupBy("department", "source")
              .pivot("stage", ["applied", "screen", "interview", "offer", "hired", "rejected"])
              .agg(F.first("applications"))
              .na.fill(0)
              .withColumn("offer_to_hire_rate",
                          F.when(F.col("offer") > 0,
                                 F.round(F.col("hired") / F.col("offer"), 4))
                           .otherwise(F.lit(0.0)))
              .withColumn("snapshot_date", F.current_date())
    )

    out = gold_path(MART)
    log.info("writing %s rows=%d -> %s", MART, pivoted.count(), out)
    pivoted.write.mode("overwrite").parquet(out)


if __name__ == "__main__":
    main()
