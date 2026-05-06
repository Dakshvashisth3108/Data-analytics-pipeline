"""Standalone Kafka consumer for audit / debugging.

This is *not* the Spark Structured Streaming consumer — that lives in
``bronze/ingest_bronze.py``. This module exists so an operator can tail a
topic from the CLI to inspect payloads, count messages, or replay from an
offset without spinning up Spark.

Usage:
    python -m consumer.audit_consumer --topic hcm.employees --group audit-1
    python -m consumer.audit_consumer --topic hcm.attendance --from-beginning
"""
from __future__ import annotations

import argparse
import json
import signal

from confluent_kafka import Consumer, KafkaError

from utils import get_logger, load_config

log = get_logger(__name__)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--topic", required=True)
    p.add_argument("--group", default="hcm-audit")
    p.add_argument("--from-beginning", action="store_true")
    p.add_argument("--max-messages", type=int, default=0, help="0 = unbounded")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    cfg = load_config()

    consumer = Consumer({
        "bootstrap.servers":  cfg.kafka.bootstrap_servers,
        "group.id":           args.group,
        "auto.offset.reset":  "earliest" if args.from_beginning else "latest",
        "enable.auto.commit": True,
        "session.timeout.ms": 6000,
    })
    consumer.subscribe([args.topic])

    stop = {"flag": False}
    def _stop(*_): stop["flag"] = True
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    seen = 0
    log.info("audit_consumer subscribed topic=%s group=%s", args.topic, args.group)
    try:
        while not stop["flag"]:
            msg = consumer.poll(1.0)
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    continue
                log.error("kafka_error=%s", msg.error())
                continue
            try:
                payload = json.loads(msg.value().decode("utf-8"))
            except Exception:
                payload = {"_raw": msg.value()[:200].decode("utf-8", errors="replace")}
            seen += 1
            log.info("offset=%d partition=%d key=%s payload=%s",
                     msg.offset(), msg.partition(),
                     msg.key().decode() if msg.key() else None, payload)
            if args.max_messages and seen >= args.max_messages:
                break
    finally:
        consumer.close()
        log.info("closed seen=%d", seen)


if __name__ == "__main__":
    main()
