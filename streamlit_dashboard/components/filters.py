"""Sidebar filter widgets, persisted across pages via session state.

Each filter is keyed so Streamlit reuses the user's selection when they
navigate between pages.
"""
from __future__ import annotations

from typing import Iterable

import pandas as pd
import streamlit as st


def _options(values: Iterable[str]) -> list[str]:
    """Drop nulls / blanks and return sorted unique strings."""
    out = sorted({v for v in values if isinstance(v, str) and v.strip()})
    return out


def department_filter(df: pd.DataFrame, *,
                      label: str = "Department",
                      key: str = "filter_department") -> list[str]:
    """Multi-select department filter. Returns the selection."""
    if df.empty or "department" not in df.columns:
        return []
    options = _options(df["department"].tolist())
    if not options:
        return []
    return st.sidebar.multiselect(
        label, options=options, default=options, key=key,
    )


def country_filter(df: pd.DataFrame, *,
                   label: str = "Country",
                   key: str = "filter_country") -> list[str]:
    if df.empty or "country" not in df.columns:
        return []
    options = _options(df["country"].tolist())
    if not options:
        return []
    return st.sidebar.multiselect(
        label, options=options, default=options, key=key,
    )


def apply_dimension_filter(df: pd.DataFrame, column: str,
                           selection: list[str]) -> pd.DataFrame:
    """Filter a DataFrame by a list of values for a given column."""
    if df.empty or not selection or column not in df.columns:
        return df
    return df[df[column].isin(selection)]
