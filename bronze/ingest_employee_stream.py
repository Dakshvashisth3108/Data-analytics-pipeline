"""Bronze layer — HCM employee Kafka stream -> Parquet (Structured Streaming).

Consumes JSON-encoded employee records from the ``hcm_employee_data``
Kafka topic, parses them against an explicit schema, augments with
ingestion metadata (``ingest_ts``, ``ingest_date``, Kafka offsets, raw
payload), and lands the result as Parquet under
``data/bronze/employees/``, partitioned by ``ingest_date``.

This is the entry point of the Medallion pipeline:

* **Bronze is intentionally permissive** — no row is dropped, dirty
  fields stay as their original strings (e.g. ``salary``,
  ``joining_date``), and ``_raw`` carries the unparsed JSON for replay.
* **All cleansing, type coercion, and SCD logic happens in Silver.**

The output schema is stable and forward-compatible with downstream
Silver / Gold transformations:

    employee_id name department salary joining_date performance_rating
    manager attrition country skills experience
    + topic partition offset kafka_ts kafka_key _raw
    + ingest_ts ingest_date  (the partition column)

Run from the project root (Windows PowerShell):

    python -m bronze.ingest_employee_stream                 # continuous
    python -m bronze.ingest_employee_stream --once          # one micro-batch and exit

Or via spark-submit (cluster-mode, automatic Kafka package handling):

    spark-submit `
      --packages org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.1 `
      bronze/ingest_employee_stream.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# sys.path bootstrap — works under both `python -m bronze.ingest_employee_stream`
# and direct invocation `python bronze/ingest_employee_stream.py`.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.streaming import StreamingQuery

from schemas import HCM_EMPLOYEE_CSV_SCHEMA
from utils import (
    Config,
    bronze_path,
    build_spark,
    checkpoint_path,
    get_logger,
    load_config,
)

LOG = get_logger("hcm.bronze.employees")
STREAM_NAME = "employees"


# ── CLI ──────────────────────────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="HCM employee Kafka stream -> Bronze Parquet",
    )
    p.add_argument(
        "--once", action="store_true",
        help="Run a single micro-batch and exit (backfill / CI).",
    )
    p.add_argument(
        "--max-rows", type=int, default=None,
        help="Override maxOffsetsPerTrigger (config default if unset).",
    )
    p.add_argument(
        "--starting-offsets", default=None,
        help='Override startingOffsets (e.g. "earliest", "latest").',
    )
    return p.parse_args()


# ── Streaming source ─────────────────────────────────────────────────────
def read_kafka_stream(
    spark: SparkSession,
    cfg: Config,
    topic: str,
    *,
    max_rows: int | None,
    starting_offsets: str | None,
) -> DataFrame:
    """Build the Kafka readStream DataFrame with safe production defaults."""
    starting = starting_offsets or cfg.streaming.starting_offsets
    cap = max_rows or cfg.streaming.max_offsets_per_trigger

    reader = (
        spark.readStream
        .format("kafka")
        .option("kafka.bootstrap.servers", cfg.kafka.bootstrap_servers)
        .option("subscribe", topic)
        .option("startingOffsets", starting)
        # In dev we tolerate data loss (e.g. broker wipe). In prod, flip to "true".
        .option("failOnDataLoss", "false")
        # Prevent a runaway micro-batch from grabbing all backlog at once.
        .option("maxOffsetsPerTrigger", cap)
    )

    LOG.info(
        "kafka_source topic=%s bootstrap=%s startingOffsets=%s maxPerTrigger=%s",
        topic, cfg.kafka.bootstrap_servers, starting, cap,
    )
    return reader.load()


# ── Parsing ──────────────────────────────────────────────────────────────
def parse_payload(raw: DataFrame) -> DataFrame:
    """Parse JSON payload against the explicit schema; keep _raw for replay.

    Spark's ``from_json`` runs in PERMISSIVE mode by default — malformed
    payloads return null for the parsed columns rather than killing the
    micro-batch. ``_raw`` carries the original JSON so replay is possible.
    """
    return (
        raw
        .select(
            F.col("topic"),
            F.col("partition"),
            F.col("offset"),
            F.col("timestamp").alias("kafka_ts"),
            F.col("key").cast("string").alias("kafka_key"),
            F.col("value").cast("string").alias("_raw"),
        )
        .withColumn("payload", F.from_json("_raw", HCM_EMPLOYEE_CSV_SCHEMA))
        .select(
            "topic", "partition", "offset", "kafka_ts",
            "kafka_key", "_raw", "payload.*",
        )
        .withColumn("ingest_ts",   F.current_timestamp())
        .withColumn("ingest_date", F.to_date("ingest_ts"))
    )


# ── Streaming sink ───────────────────────────────────────────────────────
def write_bronze(parsed: DataFrame, output: str, checkpoint: str,
                 *, once: bool, trigger_interval: str) -> StreamingQuery:
    """Write the parsed stream to Parquet, partitioned by ``ingest_date``.

    * outputMode=append — Parquet only supports append for streaming sinks.
    * checkpointLocation gives exactly-once-to-disk guarantees on retries.
    * partitionBy(ingest_date) keeps Silver's incremental reads cheap.
    """
    writer = (
        parsed.writeStream
        .format("parquet")
        .option("path", output)
        .option("checkpointLocation", checkpoint)
        .partitionBy("ingest_date")
        .outputMode("append")
        .queryName(f"bronze_{STREAM_NAME}")
    )
    # Spark 4.x deprecated trigger(once=True) -- use availableNow which
    # processes every available offset and then stops.
    writer = (
        writer.trigger(availableNow=True) if once
        else writer.trigger(processingTime=trigger_interval)
    )

    LOG.info(
        "starting_query name=bronze_%s output=%s checkpoint=%s mode=%s",
        STREAM_NAME, output, checkpoint, "availableNow" if once else trigger_interval,
    )
    return writer.start()


# ── Entrypoint ───────────────────────────────────────────────────────────
def main() -> int:
    args = parse_args()
    cfg = load_config()

    topic      = cfg.get("topics.employee_csv") or "hcm_employee_data"
    output     = bronze_path(STREAM_NAME)
    checkpoint = checkpoint_path(f"bronze_{STREAM_NAME}_stream")
    trigger    = cfg.streaming.trigger_interval

    LOG.info(
        "bronze_ingest stream=%s topic=%s output=%s checkpoint=%s trigger=%s",
        STREAM_NAME, topic, output, checkpoint,
        "once" if args.once else trigger,
    )

    # Build Spark session
    try:
        spark = build_spark(app_name=f"bronze-{STREAM_NAME}")
    except Exception:
        LOG.exception("spark_init_failed")
        return 2

    # Build the streaming pipeline
    try:
        kafka_df = read_kafka_stream(
            spark, cfg, topic,
            max_rows=args.max_rows,
            starting_offsets=args.starting_offsets,
        )
        parsed = parse_payload(kafka_df)
    except Exception:
        LOG.exception("readstream_init_failed")
        return 3

    # Start writing
    try:
        query = write_bronze(
            parsed, output, checkpoint,
            once=args.once, trigger_interval=trigger,
        )
    except Exception:
        LOG.exception("query_start_failed")
        return 4

    LOG.info("query_started id=%s name=%s", query.id, query.name)

    # Await termination — handle Ctrl+C gracefully
    try:
        query.awaitTermination()
    except KeyboardInterrupt:
        LOG.warning("keyboard_interrupt — stopping query")
        query.stop()
        LOG.info("query_stopped name=%s", query.name)
    except Exception:
        LOG.exception("query_terminated_abnormally")
        return 5

    # Log how many rows ended up landing — useful for --once / --availableNow.
    last = query.lastProgress
    if last:
        LOG.info("query_complete batchId=%s inputRows=%s sources=%s",
                 last.get("batchId"), last.get("numInputRows"),
                 [s.get("description") for s in (last.get("sources") or [])])
    else:
        LOG.info("query_complete (no batches processed -- nothing was available)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
