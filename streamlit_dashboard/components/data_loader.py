"""Cached parquet readers for the Gold layer.

All marts are read with pandas + pyarrow — Spark is *not* started in the
dashboard process. Gold marts are pre-aggregated so they're tiny (KBs to
a few MBs); pandas reads them in milliseconds and the dashboard stays
JVM-free, which makes it cheap to embed anywhere.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from utils import get_logger, gold_path

LOG = get_logger("hcm.dashboard.data")


@st.cache_data(ttl=300, show_spinner=False)
def load_gold(domain: str, metric: str) -> pd.DataFrame:
    """Load one Gold mart, returning an empty DataFrame if missing.

    Parameters
    ----------
    domain : str   e.g. ``attrition``
    metric : str   e.g. ``by_department``
    """
    path = Path(gold_path(f"{domain}/{metric}"))
    if not path.exists():
        LOG.warning("mart_missing path=%s", path)
        return pd.DataFrame()

    try:
        df = pd.read_parquet(path)
        LOG.debug("mart_loaded path=%s rows=%d", path, len(df))
        return df
    except Exception as exc:
        LOG.exception("mart_read_failed path=%s", path)
        st.error(f"Failed to load `{domain}/{metric}`: {exc}")
        return pd.DataFrame()


def have_data(*dfs: pd.DataFrame) -> bool:
    """Convenience: True if all the supplied DataFrames have rows."""
    return all(df is not None and not df.empty for df in dfs)


def empty_state(message: str = "No data available — run the Gold pipeline first.") -> None:
    """Friendly placeholder when a mart is missing."""
    st.info(message + "\n\n```\npython -m gold.build_employee_gold\n```")
