"""Visual theme for the HCM dashboard.

* Sets a wide layout + favicon.
* Injects light CSS for KPI cards and section headers.
* Exposes a consistent Plotly colour palette so every chart looks like
  it belongs to the same family.
"""
from __future__ import annotations

import streamlit as st

# Matches a calm, finance-y palette. Adjust here, see it everywhere.
PALETTE = {
    "primary":   "#0f4c81",
    "secondary": "#3aa9ff",
    "good":      "#22a06b",
    "warn":      "#f5a623",
    "bad":       "#d64545",
    "muted":     "#8a99a8",
}

PLOTLY_DISCRETE = [
    "#0f4c81", "#3aa9ff", "#22a06b", "#f5a623", "#d64545",
    "#8a99a8", "#6f42c1", "#20c997", "#fd7e14", "#0dcaf0",
]


def configure_page(title: str = "HCM Analytics", icon: str = ":bar_chart:") -> None:
    st.set_page_config(
        page_title=title,
        page_icon=icon,
        layout="wide",
        initial_sidebar_state="expanded",
    )


_CSS = """
<style>
  /* Tighter top spacing */
  .block-container {padding-top: 1.5rem; padding-bottom: 2rem;}

  /* KPI metric cards */
  div[data-testid="stMetric"] {
    background-color: #f7f9fc;
    border: 1px solid #e3e8ef;
    border-radius: 10px;
    padding: 14px 16px;
  }
  div[data-testid="stMetricLabel"] p {
    color: #5b6b7d; font-weight: 500;
  }
  div[data-testid="stMetricValue"] {
    color: #0f4c81; font-weight: 700;
  }

  /* Section headers */
  h2, h3 { color: #102a43; }
  hr { border-color: #e3e8ef; }
</style>
"""


def apply_theme(title: str = "HCM Analytics", icon: str = ":bar_chart:") -> None:
    """Call once at the top of every page."""
    configure_page(title=title, icon=icon)
    st.markdown(_CSS, unsafe_allow_html=True)
