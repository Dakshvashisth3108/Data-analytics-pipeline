"""Thin wrapper around ``confluent_kafka.Producer``.

* JSON serialisation
* Async delivery with a callback that logs failures
* Backpressure-aware: ``poll(0)`` every send + ``flush()`` on close
"""
from __future__ import annotations

import json
from typing import Any

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
