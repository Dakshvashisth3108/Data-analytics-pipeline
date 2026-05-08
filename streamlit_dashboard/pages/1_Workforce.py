"""Workforce Analytics page."""
from __future__ import annotations

import streamlit as st

from components import _bootstrap  # noqa: F401
from components.charts import bar, donut, horizontal_bar, line
from components.data_loader import (
    empty_state, have_data, load_gold,
)
from components.filters import (
    apply_dimension_filter, country_filter, department_filter,
)
from components.theme import apply_theme

apply_theme(title="HCM — Workforce")
st.title("Workforce Analytics")
st.caption("Employee distribution, seniority pyramid, and hiring velocity.")

hc_dept    = load_gold("workforce", "by_department")
hc_country = load_gold("workforce", "by_country")
exp_dist   = load_gold("workforce", "experience_distribution")
hiring     = load_gold("workforce", "hiring_trends")

if not have_data(hc_dept):
    empty_state()
    st.stop()

# ── Sidebar filters ─────────────────────────────────────────────────────
st.sidebar.header("Filters")
dept_sel    = department_filter(hc_dept)
country_sel = country_filter(hc_country)

hc_dept_f    = apply_dimension_filter(hc_dept,    "department", dept_sel)
hc_country_f = apply_dimension_filter(hc_country, "country",    country_sel)

# ── KPIs ────────────────────────────────────────────────────────────────
c1, c2, c3, c4 = st.columns(4)
c1.metric("Filtered Headcount", f"{int(hc_dept_f['headcount'].sum()):,}")
c2.metric("Active",              f"{int(hc_dept_f['active'].sum()):,}")
c3.metric("Departments Shown",   f"{hc_dept_f['department'].nunique()}")
c4.metric("Countries Shown",
          f"{hc_country_f['country'].nunique()}" if not hc_country_f.empty else "—")

st.divider()

# ── Distribution charts ────────────────────────────────────────────────
left, right = st.columns(2)
with left:
    st.subheader("By Department")
    df = hc_dept_f.sort_values("headcount", ascending=False)
    st.plotly_chart(
        bar(df, x="department", y="headcount", color="department"),
        use_container_width=True,
    )

with right:
    st.subheader("By Country")
    if have_data(hc_country_f):
        df = hc_country_f.sort_values("headcount", ascending=False)
        st.plotly_chart(
            horizontal_bar(df, category="country", value="headcount"),
            use_container_width=True,
        )
    else:
        st.info("`workforce/by_country` mart not found.")

st.divider()

# ── Experience pyramid + hiring trend ──────────────────────────────────
left, right = st.columns([1, 2])
with left:
    st.subheader("Experience Distribution")
    if have_data(exp_dist):
        st.plotly_chart(
            donut(exp_dist, names="experience_bucket", values="headcount"),
            use_container_width=True,
        )
    else:
        st.info("`workforce/experience_distribution` mart not found.")

with right:
    st.subheader("Hiring Trend")
    if have_data(hiring):
        df = hiring.copy()
        if "year_month" not in df.columns:
            df["year_month"] = (
                df["hire_year"].astype(str).str.zfill(4) + "-"
                + df["hire_month"].astype(str).str.zfill(2)
            )
        st.plotly_chart(line(df, x="year_month", y="hires"),
                        use_container_width=True)
    else:
        st.info("`workforce/hiring_trends` mart not found.")

with st.expander("Raw mart: workforce/by_department"):
    st.dataframe(hc_dept_f, use_container_width=True)
