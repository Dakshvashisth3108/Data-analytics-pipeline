"""Attrition Analytics page."""
from __future__ import annotations

import streamlit as st

from streamlit_dashboard.components import _bootstrap  # noqa: F401
from streamlit_dashboard.components.charts import bar, horizontal_bar, line
from streamlit_dashboard.components.data_loader import (
    empty_state, have_data, load_gold,
)
from streamlit_dashboard.components.filters import (
    apply_dimension_filter, country_filter, department_filter,
)
from streamlit_dashboard.components.theme import apply_theme

apply_theme(title="HCM — Attrition")
st.title("Attrition Analytics")
st.caption("Where, when, and how fast employees are leaving.")

att_dept    = load_gold("attrition", "by_department")
att_country = load_gold("attrition", "by_country")
att_cohort  = load_gold("attrition", "trend_by_cohort")
att_tenure  = load_gold("attrition", "by_tenure_bucket")

if not have_data(att_dept):
    empty_state()
    st.stop()

# ── Sidebar filters ─────────────────────────────────────────────────────
st.sidebar.header("Filters")
dept_sel    = department_filter(att_dept)
country_sel = country_filter(att_country)

att_dept_f    = apply_dimension_filter(att_dept,    "department", dept_sel)
att_country_f = apply_dimension_filter(att_country, "country",    country_sel)

# ── KPIs ────────────────────────────────────────────────────────────────
total      = int(att_dept_f["headcount"].sum())
attrited   = int(att_dept_f["attrited"].sum())
overall    = (attrited / total * 100) if total else 0.0
worst_dept = (
    att_dept_f.sort_values("attrition_rate", ascending=False).iloc[0]
    if not att_dept_f.empty else None
)
best_dept = (
    att_dept_f.sort_values("attrition_rate", ascending=True).iloc[0]
    if not att_dept_f.empty else None
)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Filtered Headcount", f"{total:,}")
c2.metric("Attrited",            f"{attrited:,}")
c3.metric("Overall Rate",        f"{overall:.2f}%")
if worst_dept is not None:
    c4.metric("Highest Dept",
              f"{worst_dept['department']}",
              delta=f"{worst_dept['attrition_rate']*100:.1f}%",
              delta_color="inverse")

st.divider()

# ── By dept + by country ───────────────────────────────────────────────
left, right = st.columns(2)
with left:
    st.subheader("Attrition Rate by Department")
    df = att_dept_f.sort_values("attrition_rate", ascending=False)
    fig = bar(df, x="department", y="attrition_rate", color="department",
              text_format="%{y:.1%}")
    fig.update_yaxes(tickformat=".0%")
    st.plotly_chart(fig, use_container_width=True)

with right:
    st.subheader("Attrition Rate by Country")
    if have_data(att_country_f):
        df = att_country_f.sort_values("attrition_rate", ascending=False)
        fig = horizontal_bar(df, category="country", value="attrition_rate")
        fig.update_xaxes(tickformat=".0%")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("`attrition/by_country` mart not found.")

st.divider()

# ── Cohort + tenure ────────────────────────────────────────────────────
left, right = st.columns(2)
with left:
    st.subheader("Attrition by Hire Cohort")
    if have_data(att_cohort):
        df = att_cohort.sort_values("hire_year")
        fig = line(df, x="hire_year", y="attrition_rate")
        fig.update_yaxes(tickformat=".0%")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("`attrition/trend_by_cohort` mart not found.")

with right:
    st.subheader("Attrition by Tenure Bucket")
    if have_data(att_tenure):
        bucket_order = ["0-1y", "1-3y", "3-5y", "5-10y", "10y+"]
        df = att_tenure.copy()
        df["tenure_bucket"] = df["tenure_bucket"].astype("category")
        df["tenure_bucket"] = df["tenure_bucket"].cat.set_categories(
            bucket_order, ordered=True
        )
        df = df.sort_values("tenure_bucket")
        fig = bar(df, x="tenure_bucket", y="attrition_rate")
        fig.update_yaxes(tickformat=".0%")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("`attrition/by_tenure_bucket` mart not found.")

with st.expander("Raw mart: attrition/by_department"):
    st.dataframe(att_dept_f, use_container_width=True)
