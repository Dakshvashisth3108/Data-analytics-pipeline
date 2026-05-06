"""Bronze layer — Kafka -> Parquet (raw, append-only).

Spark Structured Streaming reads JSON events from a Kafka topic, parses them
against the registered schema, adds ingest metadata, and writes to a
date-partitioned Parquet table under ``data/bronze/<stream>/``.

Bronze is intentionally **schema-on-read with explicit StructType** — we keep
the original payload as a string column ``_raw`` for replay, and we never
mutate or filter rows here. All cleansing happens in Silver.

Usage:
    spark-submit bronze/ingest_bronze.py --stream employees
    spark-submit bronze/ingest_bronze.py --stream attendance --once
"""
from __future__ import annotations

import argparse

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from schemas import SCHEMAS_BY_STREAM
from utils import build_spark, bronze_path, checkpoint_path, get_logger, load_config

log = get_logger(__name__)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--stream", required=True,
                   choices=["employees", "attendance", "performance", "recruitment"])
    p.add_argument("--once", action="store_true",
                   help="Run a single micro-batch and exit (useful for backfills/CI).")
    return p.parse_args()


def _read_kafka(spark: SparkSession, cfg, topic: str) -> DataFrame:
    return (
        spark.readStream
        .format("kafka")
        .option("kafka.bootstrap.servers", cfg.kafka.bootstrap_servers)
        .option("subscribe", topic)
        .option("startingOffsets", cfg.streaming.starting_offsets)
        .option("maxOffsetsPerTrigger", cfg.streaming.max_offsets_per_trigger)
        .option("failOnDataLoss", "false")
        .load()
    )


def _parse_payload(raw: DataFrame, stream: str) -> DataFrame:
    schema = SCHEMAS_BY_STREAM[stream]
    return (
        raw.select(
            F.col("topic"),
            F.col("partition"),
            F.col("offset"),
            F.col("timestamp").alias("kafka_ts"),
            F.col("key").cast("string").alias("kafka_key"),
            F.col("value").cast("string").alias("_raw"),
        )
        .withColumn("payload", F.from_json(F.col("_raw"), schema))
        .select("topic", "partition", "offset", "kafka_ts",
                "kafka_key", "_raw", "payload.*")
        .withColumn("ingest_ts",   F.current_timestamp())
        .withColumn("ingest_date", F.to_date(F.col("ingest_ts")))
    )


def main() -> None:
    args = _parse_args()
    cfg  = load_config()
    spark = build_spark(app_name=f"bronze-{args.stream}")

    topic = cfg.topics.__getattr__(args.stream)
    out   = bronze_path(args.stream)
    chk   = checkpoint_path(f"bronze_{args.stream}")
    log.info("bronze ingest stream=%s topic=%s out=%s", args.stream, topic, out)

    raw    = _read_kafka(spark, cfg, topic)
    parsed = _parse_payload(raw, args.stream)

    writer = (
        parsed.writeStream
        .format("parquet")
        .option("path", out)
        .option("checkpointLocation", chk)
        .partitionBy("ingest_date")
        .outputMode("append")
    )
    writer = writer.trigger(once=True) if args.once \
        else writer.trigger(processingTime=cfg.streaming.trigger_interval)

    query = writer.start()
    query.awaitTermination()


if __name__ == "__main__":
    main()
