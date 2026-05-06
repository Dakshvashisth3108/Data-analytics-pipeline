"""Typed config loader.

Loads ``configs/app.yaml`` and applies environment-variable overrides using
double-underscore notation (``KAFKA__BOOTSTRAP_SERVERS=...`` -> ``cfg.kafka.bootstrap_servers``).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_CFG = _ROOT / "configs" / "app.yaml"


@dataclass
class Config:
    raw: dict[str, Any] = field(default_factory=dict)

    def __getattr__(self, item: str) -> Any:
        try:
            value = self.raw[item]
        except KeyError as exc:
            raise AttributeError(item) from exc
        return Config(value) if isinstance(value, dict) else value

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.raw
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node


def _apply_env_overrides(cfg: dict[str, Any]) -> dict[str, Any]:
    """Override leaf values via env vars like ``LAKE__ROOT=/mnt/lake``."""
    for key, value in os.environ.items():
        if "__" not in key:
            continue
        path = [p.lower() for p in key.split("__")]
        cursor = cfg
        for part in path[:-1]:
            if part not in cursor or not isinstance(cursor[part], dict):
                cursor = None
                break
            cursor = cursor[part]
        if cursor is None or path[-1] not in cursor:
            continue
        cursor[path[-1]] = _coerce(value, cursor[path[-1]])
    return cfg


def _coerce(value: str, reference: Any) -> Any:
    if isinstance(reference, bool):
        return value.lower() in {"1", "true", "yes", "on"}
    if isinstance(reference, int):
        return int(value)
    if isinstance(reference, float):
        return float(value)
    return value


def load_config(path: str | Path | None = None) -> Config:
    cfg_path = Path(path) if path else _DEFAULT_CFG
    with cfg_path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    data = _apply_env_overrides(data)
    return Config(data)
