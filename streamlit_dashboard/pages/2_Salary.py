"""Salary Analytics page."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from streamlit_dashboard.components import _bootstrap  # noqa: F401
from streamlit_dashboard.components.charts import bar, horizontal_bar
from streamlit_dashboard.components.data_loader import (
    empty_state, have_data, load_gold,
)
from streamlit_dashboard.components.filters import (
    apply_dimension_filter, department_filter,
)
from streamlit_dashboard.components.theme import apply_theme

apply_theme(title="HCM — Salary")
st.title("Salary Analytics")
st.caption("Pay levels, top-paying departments, and the company-wide distribution.")

salary_dept   = load_gold("salary", "by_department")
top_paying    = load_gold("salary", "top_paying_depts")
salary_dist   = load_gold("salary", "distribution")

if not have_data(salary_dept):
    empty_state()
    st.stop()

# ── Sidebar filters ─────────────────────────────────────────────────────
st.sidebar.header("Filters")
dept_sel = department_filter(salary_dept)
salary_dept_f = apply_dimension_filter(salary_dept, "department", dept_sel)

# ── Company KPIs ────────────────────────────────────────────────────────
if have_data(salary_dist):
    s = salary_dist.iloc[0]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Avg Salary",     f"₹{s['avg_salary']:,.0f}")
    c2.metric("Median",         f"₹{s['median_salary']:,.0f}")
    c3.metric("P90",            f"₹{s.get('p90_salary', 0):,.0f}")
    c4.metric("Total Payroll",  f"₹{s['total_payroll']:,.0f}")

st.divider()

# ── Avg salary by dept ─────────────────────────────────────────────────
st.subheader("Average Salary by Department")
df = salary_dept_f.sort_values("avg_salary", ascending=False)
st.plotly_chart(
    bar(df, x="department", y="avg_salary", color="department",
        text_format="₹%{y:,.0f}"),
    use_container_width=True,
)

# ── Distribution chart (range bar from p25/median/p75) ─────────────────
st.subheader("Salary Spread (P25 – Median – P75) by Department")
spread_cols = {"p25_salary", "median_salary", "p75_salary"}
if spread_cols.issubset(salary_dept_f.columns):
    spread_df = salary_dept_f[
        ["department", "p25_salary", "median_salary", "p75_salary",
         "min_salary", "max_salary"]
    ].sort_values("median_salary", ascending=True)
    melt = spread_df.melt(id_vars="department",
                          value_vars=["p25_salary", "median_salary", "p75_salary"],
                          var_name="percentile", value_name="salary")
    st.plotly_chart(
        bar(melt, x="department", y="salary", color="percentile",
            orientation="v"),
        use_container_width=True,
    )
else:
    st.info("Distribution columns (p25/median/p75) not found in mart.")

st.divider()

# ── Top paying ─────────────────────────────────────────────────────────
st.subheader("Top-Paying Departments")
if have_data(top_paying):
    st.plotly_chart(
        horizontal_bar(top_paying, category="department", value="avg_salary"),
        use_container_width=True,
    )
    st.dataframe(
        top_paying[["rank", "department", "avg_salary", "median_salary",
                    "employees_with_salary", "total_payroll"]],
        use_container_width=True,
    )
else:
    st.info("`salary/top_paying_depts` mart not found.")

with st.expander("Raw mart: salary/by_department"):
    st.dataframe(salary_dept_f, use_container_width=True)
