"""Shared helpers for domain chunkers."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from utils import get_logger, gold_path

LOG = get_logger("hcm.embeddings.chunkers")


def load_mart(domain: str, metric: str) -> pd.DataFrame:
    """Read one Gold mart from disk; return empty DataFrame if missing."""
    path = Path(gold_path(f"{domain}/{metric}"))
    if not path.exists():
        LOG.warning("mart_missing path=%s", path)
        return pd.DataFrame()
    try:
        return pd.read_parquet(path)
    except Exception:
        LOG.exception("mart_read_failed path=%s", path)
        return pd.DataFrame()


def fmt_money(value, currency: str = "INR") -> str:
    """Format a numeric salary in human-readable form."""
    if value is None or pd.isna(value):
        return "n/a"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    if v >= 1e7:
        return f"{currency} {v/1e7:.2f} Cr"
    if v >= 1e5:
        return f"{currency} {v/1e5:.2f} L"
    return f"{currency} {v:,.0f}"


def fmt_pct(value, digits: int = 1) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{v*100:.{digits}f}%"


def safe_int(value) -> int:
    if value is None or pd.isna(value):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def base_metadata(domain: str, metric: str, snapshot_date=None,
                  **extras) -> dict:
    """Standard metadata stamped on every chunk for that mart."""
    meta = {
        "domain": domain,
        "metric": metric,
        "source_mart": f"gold/{domain}/{metric}",
    }
    if snapshot_date is not None:
        meta["snapshot_date"] = str(snapshot_date)
    meta.update(extras)
    return meta
