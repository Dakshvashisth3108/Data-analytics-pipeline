"""Lakehouse path helpers.

Single place that knows the layout under ``data/``. Swap implementations here
to move between local FS, S3, ADLS, etc., without touching job code.
"""
from __future__ import annotations

from pathlib import Path

from .config import Config, load_config


def _root(cfg: Config | None, key: str) -> str:
    cfg = cfg or load_config()
    return cfg.get(f"lake.{key}")


def bronze_path(stream: str, cfg: Config | None = None) -> str:
    return str(Path(_root(cfg, "bronze")) / stream)


def silver_path(table: str, cfg: Config | None = None) -> str:
    return str(Path(_root(cfg, "silver")) / table)


def gold_path(mart: str, cfg: Config | None = None) -> str:
    return str(Path(_root(cfg, "gold")) / mart)


def checkpoint_path(job: str, cfg: Config | None = None) -> str:
    return str(Path(_root(cfg, "checkpoints")) / job)
