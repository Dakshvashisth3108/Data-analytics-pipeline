"""Thin wrapper around ``confluent_kafka.Producer``.

This module is a **library** — it exposes the ``HcmKafkaProducer`` class
used by other producers (e.g. ``producer.run``). It is **not** a CLI
entry point. To stream data, run one of:

    python -m producer.csv_to_kafka     # CSV file -> Kafka
    python -m producer.run --stream all # synthetic Faker events -> Kafka
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# Bootstrap so `from utils import ...` works when this module is imported
# directly (e.g. `python producer/kafka_producer.py`) as well as via the
# `producer` package.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from confluent_kafka import Producer

from utils import get_logger, load_config

log = get_logger(__name__)


class HcmKafkaProducer:
    def __init__(self, cfg=None) -> None:
        cfg = cfg or load_config()
        kcfg = cfg.kafka
        self._producer = Producer({
            "bootstrap.servers": kcfg.bootstrap_servers,
            "client.id":         kcfg.client_id,
            "acks":              kcfg.acks,
            "compression.type":  kcfg.compression_type,
            "linger.ms":         kcfg.linger_ms,
            "retries":           kcfg.retries,
            "enable.idempotence": True,
        })

    @staticmethod
    def _on_delivery(err, msg) -> None:
        if err is not None:
            log.error("delivery_failed topic=%s err=%s", msg.topic(), err)

    def send(self, topic: str, value: dict[str, Any], key: str | None = None) -> None:
        self._producer.produce(
            topic=topic,
            key=key.encode("utf-8") if key else None,
            value=json.dumps(value, default=str).encode("utf-8"),
            on_delivery=self._on_delivery,
        )
        self._producer.poll(0)

    def flush(self, timeout: float = 10.0) -> None:
        self._producer.flush(timeout)


if __name__ == "__main__":
    # This file is a library, not an entry point. Print a friendly
    # redirect so users who run it by mistake don't get a silent no-op.
    print(
        "producer/kafka_producer.py is a library module (HcmKafkaProducer).\n"
        "It is not meant to be run directly.\n"
        "\n"
        "To stream data, run one of:\n"
        "  python -m producer.csv_to_kafka       # CSV  -> Kafka\n"
        "  python -m producer.run --stream all   # synthetic Faker events\n",
        file=sys.stderr,
    )
    sys.exit(2)
