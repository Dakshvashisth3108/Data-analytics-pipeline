"""Streamlit BI dashboard — reads Gold parquet marts directly with pandas.

The dashboard intentionally avoids Spark at read time: Gold marts are small
aggregates, so pandas + pyarrow is sub-second and doesn't need a JVM.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

# Make ``utils`` importable when launching from project root or anywhere else.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils import gold_path  # noqa: E402

st.set_page_config(page_title="HCM Analytics", layout="wide", page_icon="📊")


@st.cache_data(ttl=300)
def _load(mart: str) -> pd.DataFrame:
    path = Path(gold_path(mart))
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


# ── Sidebar ─────────────────────────────────────────────────────────────────
st.sidebar.title("HCM Analytics")
page = st.sidebar.radio("View", ["Headcount", "Attendance", "Performance", "Recruitment"])
st.sidebar.caption("Data source: Gold parquet marts under ./data/gold")

# ── Pages ───────────────────────────────────────────────────────────────────
if page == "Headcount":
    st.title("Headcount & Attrition")
    df = _load("gold_headcount")
    if df.empty:
        st.info("No data yet. Run the gold headcount job first.")
    else:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total headcount", int(df["headcount"].sum()))
        c2.metric("Active",          int(df["active_headcount"].sum()))
        c3.metric("Attrition",       int(df["attrition_count"].sum()))
        c4.metric("Avg salary (₹)",  f"{df['avg_salary'].mean():,.0f}")

        st.plotly_chart(
            px.bar(df, x="department", y="headcount", color="location",
                   title="Headcount by department"),
            use_container_width=True,
        )
        st.plotly_chart(
            px.bar(df, x="department", y="attrition_rate", color="location",
                   title="Attrition rate by department"),
            use_container_width=True,
        )
        st.dataframe(df, use_container_width=True)

elif page == "Attendance":
    st.title("Attendance Compliance")
    df = _load("gold_attendance_compliance")
    if df.empty:
        st.info("No data yet.")
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("Avg attendance rate",
                  f"{df['attendance_rate'].mean()*100:.1f}%")
        c2.metric("Total late",  int(df["late_count"].sum()))
        c3.metric("Avg hours",   f"{df['avg_hours_worked'].mean():.1f}")

        st.plotly_chart(
            px.bar(df, x="department", y="attendance_rate", color="location",
                   title="Attendance rate"),
            use_container_width=True,
        )
        st.dataframe(df, use_container_width=True)

elif page == "Performance":
    st.title("Performance Distribution")
    df = _load("gold_performance")
    if df.empty:
        st.info("No data yet.")
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("Reviews",         int(df["reviews"].sum()))
        c2.metric("Avg rating",      f"{df['avg_rating'].mean():.2f}")
        c3.metric("HP share",        f"{df['hp_share'].mean()*100:.1f}%")

        st.plotly_chart(
            px.bar(df, x="department", y="avg_rating", color="cycle",
                   barmode="group", title="Average rating per cycle"),
            use_container_width=True,
        )
        st.plotly_chart(
            px.scatter(df, x="reviews", y="hp_share", size="total_bonus",
                       color="department", title="High-performer share vs reviews"),
            use_container_width=True,
        )
        st.dataframe(df, use_container_width=True)

elif page == "Recruitment":
    st.title("Recruitment Funnel")
    df = _load("gold_recruitment_funnel")
    if df.empty:
        st.info("No data yet.")
    else:
        c1, c2 = st.columns(2)
        c1.metric("Total hires", int(df["hired"].sum()))
        c2.metric("Avg offer→hire rate",
                  f"{df['offer_to_hire_rate'].mean()*100:.1f}%")

        stages = ["applied", "screen", "interview", "offer", "hired"]
        funnel = df[stages].sum().reset_index()
        funnel.columns = ["stage", "count"]
        st.plotly_chart(
            px.funnel(funnel, x="count", y="stage",
                      title="Overall funnel"),
            use_container_width=True,
        )
        st.plotly_chart(
            px.bar(df, x="source", y="hired", color="department",
                   title="Hires by source"),
            use_container_width=True,
        )
        st.dataframe(df, use_container_width=True)
