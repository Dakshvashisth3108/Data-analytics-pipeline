"""Centralised logger factory.

All modules should call ``get_logger(__name__)`` rather than configuring
``logging`` directly. The first call initialises handlers from
``configs/logging.yaml``; subsequent calls reuse them.
"""
from __future__ import annotations

import logging
import logging.config
from pathlib import Path
from threading import Lock

import yaml

_ROOT = Path(__file__).resolve().parents[1]
_CFG = _ROOT / "configs" / "logging.yaml"
_initialised = False
_lock = Lock()


def _init() -> None:
    global _initialised
    with _lock:
        if _initialised:
            return
        (_ROOT / "logs").mkdir(exist_ok=True)
        if _CFG.exists():
            with _CFG.open("r", encoding="utf-8") as fh:
                logging.config.dictConfig(yaml.safe_load(fh))
        else:
            logging.basicConfig(level=logging.INFO)
        _initialised = True


def get_logger(name: str) -> logging.Logger:
    _init()
    return logging.getLogger(name)
