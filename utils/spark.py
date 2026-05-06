"""SparkSession factory configured from ``configs/app.yaml``."""
from __future__ import annotations

from pyspark.sql import SparkSession

from .config import Config, load_config


def build_spark(app_name: str | None = None, cfg: Config | None = None) -> SparkSession:
    cfg = cfg or load_config()
    spark_cfg = cfg.spark

    builder = (
        SparkSession.builder
        .appName(app_name or spark_cfg.app_name)
        .master(spark_cfg.master)
        .config("spark.sql.shuffle.partitions", spark_cfg.shuffle_partitions)
        .config("spark.serializer", spark_cfg.serializer)
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.adaptive.enabled", "true")
        .config("spark.sql.adaptive.coalescePartitions.enabled", "true")
    )

    packages = cfg.get("spark.packages") or []
    if packages:
        builder = builder.config("spark.jars.packages", ",".join(packages))

    spark = builder.getOrCreate()
    spark.sparkContext.setLogLevel("WARN")
    return spark
