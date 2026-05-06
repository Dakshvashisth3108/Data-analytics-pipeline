"""HCM CSV -> Kafka streamer (confluent-kafka, production-style).

Reads ``data/raw/hcm_employees.csv`` and publishes each row as a JSON
message to the ``hcm_employee_data`` topic on ``localhost:9092``.

Design choices
--------------
* **confluent-kafka** for the high-performance librdkafka client.
* **Idempotent producer + acks=all** so a retry won't duplicate or lose.
* **Config-driven**: broker, topic, pacing — all in ``configs/app.yaml``.
* **Structured logging** via ``utils.get_logger`` (rotating JSON file +
  console).
* **Per-message delivery callbacks** for accurate sent/failed counts.
* **Backpressure-aware**: catches BufferError, polls, retries the send.
* **Continuous streaming**: when the file ends, loop back to the top
  until interrupted (``--no-loop`` to disable).
* **Graceful shutdown**: SIGINT/SIGTERM stop the loop, flush in-flight,
  close cleanly.

Run from the project root:
    python -m producer.csv_to_kafka                          # continuous
    python -m producer.csv_to_kafka --max-records 200        # bounded
    python -m producer.csv_to_kafka --delay 0.5 --no-loop    # slow demo
"""
from __future__ import annotations

import argparse
import json
import math
import random
import signal
import sys
import time
from pathlib import Path
from typing import Any, Callable, Iterator

# ── sys.path bootstrap ────────────────────────────────────────────────────
# Ensures `from utils import ...` works whether you run this file as
# `python -m producer.csv_to_kafka` or `python producer/csv_to_kafka.py`.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd
from confluent_kafka import KafkaError, KafkaException, Producer

from utils import Config, get_logger, load_config

LOG = get_logger("hcm.producer.csv")

KEY_FIELD: str = "employee_id"
SKILLS_FIELD: str = "skills"
SKILLS_SEPARATOR: str = "|"


# ── Producer factory ──────────────────────────────────────────────────────
def build_producer(cfg: Config) -> Producer:
    """Build an idempotent confluent-kafka producer from app config.

    Idempotence requires acks=all and bounded in-flight; librdkafka manages
    retries internally via ``message.send.max.retries`` so we don't expose
    a separate ``retries`` knob — it would conflict with idempotence.
    """
    kcfg = cfg.kafka
    conf: dict[str, Any] = {
        "bootstrap.servers":             kcfg.bootstrap_servers,
        "client.id":                     kcfg.client_id,
        "acks":                          "all",
        "enable.idempotence":            True,
        "compression.type":              kcfg.compression_type,
        "linger.ms":                     int(kcfg.linger_ms),
        "retry.backoff.ms":              500,
        "request.timeout.ms":            30_000,
        "delivery.timeout.ms":           120_000,
        "queue.buffering.max.messages":  100_000,
        "queue.buffering.max.kbytes":    1_048_576,  # 1 GiB
        "socket.keepalive.enable":       True,
    }
    LOG.info("kafka_producer config bootstrap=%s client_id=%s",
             conf["bootstrap.servers"], conf["client.id"])
    return Producer(conf)


# ── Row hygiene ───────────────────────────────────────────────────────────
def clean_record(row: dict[str, Any]) -> dict[str, Any]:
    """Make one CSV row JSON-safe.

    pandas surfaces missing cells as ``float('nan')`` — not valid JSON.
    Skills come back as a pipe-delimited string; rebuild the original list.
    """
    out: dict[str, Any] = {}
    for k, v in row.items():
        if v is None or v is pd.NA:
            out[k] = None
        elif isinstance(v, float) and math.isnan(v):
            out[k] = None
        else:
            out[k] = v

    skills = out.get(SKILLS_FIELD)
    if isinstance(skills, str):
        out[SKILLS_FIELD] = [s for s in skills.split(SKILLS_SEPARATOR) if s]
    return out


# ── Delivery callback ─────────────────────────────────────────────────────
class DeliveryCounter:
    """Aggregates per-message delivery results from the broker."""

    def __init__(self, log_every_failure: bool = True) -> None:
        self.delivered: int = 0
        self.failed: int = 0
        self._log_failures = log_every_failure

    def __call__(self, err: KafkaError | None, msg) -> None:
        if err is not None:
            self.failed += 1
            if self._log_failures:
                LOG.error("delivery_failed topic=%s err=%s",
                          msg.topic() if msg else "?", err)
            return
        self.delivered += 1
        LOG.debug("delivered topic=%s partition=%d offset=%d",
                  msg.topic(), msg.partition(), msg.offset())


# ── Streamer ──────────────────────────────────────────────────────────────
class CsvKafkaStreamer:
    """Reads rows from a factory and produces JSON messages to Kafka.

    The factory is a zero-arg callable returning a fresh iterator each call.
    That lets us cheaply re-iterate the dataframe when ``loop=True``.
    """

    def __init__(
        self,
        producer: Producer,
        topic: str,
        *,
        delay: float = 0.05,
        jitter: float = 0.5,
        progress_every: int = 1_000,
    ) -> None:
        self.producer = producer
        self.topic = topic
        self.delay = max(0.0, delay)
        self.jitter = max(0.0, min(jitter, 1.0))
        self.progress_every = progress_every
        self.callback = DeliveryCounter()
        self._rng = random.Random()
        self._stop = False

    def request_stop(self) -> None:
        self._stop = True

    # ── helpers ────────────────────────────────────────────────────────────
    def _pace(self) -> None:
        if self.delay <= 0:
            return
        spread = self._rng.uniform(-self.jitter, self.jitter) * self.delay
        time.sleep(max(0.0, self.delay + spread))

    def _serialize(self, record: dict[str, Any]) -> bytes:
        return json.dumps(record, default=str, ensure_ascii=False).encode("utf-8")

    def _produce_one(self, record: dict[str, Any]) -> None:
        """Send a single record, polling on BufferError to drain the queue."""
        key = record.get(KEY_FIELD)
        key_bytes = str(key).encode("utf-8") if key is not None else None
        value_bytes = self._serialize(record)

        for attempt in (1, 2):
            try:
                self.producer.produce(
                    topic=self.topic,
                    key=key_bytes,
                    value=value_bytes,
                    callback=self.callback,
                )
                return
            except BufferError:
                LOG.warning("buffer_full attempt=%d — polling broker for room", attempt)
                self.producer.poll(1.0)
            except KafkaException as exc:
                LOG.error("kafka_exception key=%s err=%s", key, exc)
                self.callback.failed += 1
                return
        LOG.error("buffer_still_full key=%s — dropping record", key)
        self.callback.failed += 1

    # ── main loop ──────────────────────────────────────────────────────────
    def stream(
        self,
        rows_factory: Callable[[], Iterator[dict[str, Any]]],
        *,
        loop: bool,
        max_records: int = 0,
    ) -> dict[str, int]:
        attempted = 0
        passes = 0

        while True:
            passes += 1
            for raw in rows_factory():
                if self._stop:
                    LOG.warning("stop_requested attempted=%d", attempted)
                    return self._summary(attempted, passes)
                if max_records and attempted >= max_records:
                    LOG.info("max_records_reached n=%d", max_records)
                    return self._summary(attempted, passes)

                try:
                    record = clean_record(raw)
                    self._produce_one(record)
                    attempted += 1
                except Exception:
                    LOG.exception("record_error key=%s", raw.get(KEY_FIELD))
                    self.callback.failed += 1

                # poll(0) services delivery callbacks without blocking
                self.producer.poll(0)

                if attempted % self.progress_every == 0:
                    LOG.info("progress attempted=%d delivered=%d failed=%d pass=%d",
                             attempted, self.callback.delivered,
                             self.callback.failed, passes)
                self._pace()

            if not loop:
                LOG.info("end_of_file pass=%d (loop disabled)", passes)
                return self._summary(attempted, passes)
            LOG.info("end_of_file pass=%d — restarting from row 0", passes)

    def _summary(self, attempted: int, passes: int) -> dict[str, int]:
        return {
            "attempted": attempted,
            "delivered": self.callback.delivered,
            "failed":    self.callback.failed,
            "passes":    passes,
        }


# ── CLI ───────────────────────────────────────────────────────────────────
def parse_args(cfg: Config) -> argparse.Namespace:
    pcfg = cfg.get("producer.csv") or {}
    p = argparse.ArgumentParser(description="HCM CSV -> Kafka (confluent-kafka)")
    p.add_argument("--csv",         type=Path,
                   default=Path(pcfg.get("default_path", "data/raw/hcm_employees.csv")))
    p.add_argument("--topic",       default=None,
                   help="Override topic; default from configs/app.yaml -> topics.employee_csv")
    p.add_argument("--delay",       type=float,
                   default=float(pcfg.get("delay_seconds", 0.05)))
    p.add_argument("--jitter",      type=float,
                   default=float(pcfg.get("jitter", 0.5)))
    p.add_argument("--max-records", type=int, default=0,
                   help="Stop after N records; 0 = unbounded")
    p.add_argument("--loop",    dest="loop", action="store_true",
                   default=bool(pcfg.get("loop", True)),
                   help="Loop the CSV continuously (default)")
    p.add_argument("--no-loop", dest="loop", action="store_false")
    return p.parse_args()


def main() -> int:
    cfg = load_config()
    args = parse_args(cfg)
    topic = args.topic or cfg.get("topics.employee_csv") or "hcm_employee_data"

    if not args.csv.exists():
        LOG.error("csv_not_found path=%s — generate first via "
                  "`python scripts/generate_hcm_dataset.py`", args.csv)
        return 2

    LOG.info("loading csv path=%s", args.csv)
    df = pd.read_csv(args.csv)
    LOG.info("loaded rows=%d cols=%d", len(df), len(df.columns))
    LOG.info("target topic=%s bootstrap=%s loop=%s delay=%.3fs jitter=%.2f",
             topic, cfg.kafka.bootstrap_servers, args.loop, args.delay, args.jitter)

    try:
        producer = build_producer(cfg)
    except KafkaException:
        LOG.exception("producer_init_failed")
        return 3

    streamer = CsvKafkaStreamer(
        producer, topic,
        delay=args.delay,
        jitter=args.jitter,
        progress_every=int(cfg.get("producer.csv.progress_every", 1000)),
    )

    def _on_signal(signum, _frame) -> None:
        LOG.warning("signal_received signum=%d — graceful shutdown", signum)
        streamer.request_stop()
    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    # rows_factory rewinds the dataframe so loop=True can re-iterate
    records: list[dict[str, Any]] = df.to_dict(orient="records")
    rows_factory: Callable[[], Iterator[dict[str, Any]]] = lambda: iter(records)

    started = time.time()
    flush_timeout = float(cfg.get("producer.csv.flush_timeout_seconds", 30))
    attempted = passes = 0
    try:
        intermediate = streamer.stream(
            rows_factory, loop=args.loop, max_records=args.max_records,
        )
        attempted = intermediate["attempted"]
        passes = intermediate["passes"]
    except KafkaException:
        LOG.exception("fatal_kafka_error")
        return 5
    finally:
        # IMPORTANT: read delivered/failed AFTER flush — most callbacks fire
        # during flush, not during the produce loop.
        LOG.info("flushing pending messages timeout=%.0fs ...", flush_timeout)
        remaining = producer.flush(flush_timeout)
        if remaining:
            LOG.warning("flush_timed_out remaining=%d (delivery.timeout.ms may "
                        "have not yet expired — messages may still arrive)", remaining)

    delivered = streamer.callback.delivered
    failed = streamer.callback.failed
    elapsed = max(time.time() - started, 1e-9)
    rate = delivered / elapsed
    LOG.info(
        "done attempted=%d delivered=%d failed=%d passes=%d elapsed=%.1fs rate=%.1f msg/s",
        attempted, delivered, failed, passes, elapsed, rate,
    )
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
