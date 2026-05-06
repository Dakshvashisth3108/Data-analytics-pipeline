"""CLI entrypoint for the HCM event simulator.

Usage (preferred — module form):
    python -m producer.run --stream employees --rate 50 --duration 600
    python -m producer.run --stream attendance --rate 200
    python -m producer.run --stream all --rate 30

Direct invocation also works thanks to the sys.path bootstrap below:
    python producer/run.py --stream all --rate 30
"""
from __future__ import annotations

import argparse
import signal
import sys
import time
from pathlib import Path

# Bootstrap so absolute imports resolve when run as a script.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from utils import get_logger, load_config

from producer.generators import HcmGenerator
from producer.kafka_producer import HcmKafkaProducer

log = get_logger(__name__)

KEY_FIELDS = {
    "employees":   "employee_id",
    "attendance":  "attendance_id",
    "performance": "review_id",
    "recruitment": "application_id",
}


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="HCM Kafka event producer")
    p.add_argument("--stream", required=True,
                   choices=["employees", "attendance", "performance", "recruitment", "all"])
    p.add_argument("--rate", type=int, default=25, help="Events per second")
    p.add_argument("--duration", type=int, default=0, help="Seconds to run; 0 = forever")
    p.add_argument("--seed", type=int, default=42)
    return p.parse_args()


def _run_one(stream: str, gen: HcmGenerator, prod: HcmKafkaProducer,
             topic: str, rate: int, deadline: float | None) -> None:
    interval = 1.0 / max(rate, 1)
    key_field = KEY_FIELDS[stream]
    n = 0
    for event in gen.stream(stream):
        prod.send(topic, event, key=str(event[key_field]))
        n += 1
        if n % 500 == 0:
            log.info("produced stream=%s count=%d", stream, n)
        if deadline and time.time() >= deadline:
            break
        time.sleep(interval)
    log.info("stopped stream=%s total=%d", stream, n)


def main() -> None:
    args = _parse_args()
    cfg = load_config()
    gen = HcmGenerator(seed=args.seed)
    prod = HcmKafkaProducer(cfg)
    deadline = time.time() + args.duration if args.duration > 0 else None

    stop = {"flag": False}

    def _stop(*_): stop["flag"] = True
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    streams = ["employees", "attendance", "performance", "recruitment"] \
              if args.stream == "all" else [args.stream]

    log.info("starting producer streams=%s rate=%d duration=%s",
             streams, args.rate, args.duration or "inf")
    try:
        # Round-robin across streams when "all" is selected
        if len(streams) == 1:
            _run_one(streams[0], gen, prod, cfg.topics.__getattr__(streams[0]),
                     args.rate, deadline)
        else:
            interval = 1.0 / max(args.rate, 1)
            iters = {s: gen.stream(s) for s in streams}
            counts = {s: 0 for s in streams}
            while not stop["flag"]:
                for s in streams:
                    event = next(iters[s])
                    topic = cfg.topics.__getattr__(s)
                    prod.send(topic, event, key=str(event[KEY_FIELDS[s]]))
                    counts[s] += 1
                if deadline and time.time() >= deadline:
                    break
                time.sleep(interval)
            log.info("totals=%s", counts)
    finally:
        prod.flush()
        log.info("flushed and exiting")


if __name__ == "__main__":
    main()
