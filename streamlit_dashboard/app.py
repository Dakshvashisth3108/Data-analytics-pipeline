"""HCM Analytics — Executive Overview (home page).

Run from the project root:
    streamlit run streamlit_dashboard/app.py

The home page surfaces the four C-suite metrics + a couple of trend
charts. Detailed pages live under ``pages/`` and are auto-discovered
by Streamlit's multipage app feature.
"""
from __future__ import annotations

import streamlit as st

from streamlit_dashboard.components import _bootstrap  # noqa: F401  -- sys.path
from streamlit_dashboard.components.charts import bar, line
from streamlit_dashboard.components.data_loader import (
    empty_state,
    have_data,
    load_gold,
)
from streamlit_dashboard.components.theme import apply_theme

apply_theme(title="HCM Analytics", icon=":bar_chart:")

st.title("HCM Analytics — Executive Overview")
st.caption(
    "Source: Gold parquet marts under `data/gold/`. "
    "Use the sidebar to navigate to deep-dive pages."
)

# ── Load marts ──────────────────────────────────────────────────────────
hc_dept     = load_gold("workforce", "by_department")
hc_country  = load_gold("workforce", "by_country")
salary_dist = load_gold("salary",    "distribution")
top_paying  = load_gold("salary",    "top_paying_depts")
hiring      = load_gold("workforce", "hiring_trends")

if not have_data(hc_dept, salary_dist):
    empty_state()
    st.stop()

# ── KPIs ────────────────────────────────────────────────────────────────
total_employees   = int(hc_dept["headcount"].sum())
total_departments = int(hc_dept["department"].nunique())
total_attrited    = int(hc_dept["attrited"].sum())
attrition_pct     = (total_attrited / total_employees * 100) if total_employees else 0.0
total_countries   = int(hc_country["country"].nunique()) if not hc_country.empty else 0

avg_salary = float(salary_dist["avg_salary"].iloc[0]) if not salary_dist.empty else 0.0
total_payroll = (
    float(salary_dist["total_payroll"].iloc[0])
    if (not salary_dist.empty and "total_payroll" in salary_dist.columns) else 0.0
)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Total Employees", f"{total_employees:,}")
c2.metric("Departments",     f"{total_departments}")
c3.metric("Attrition Rate",  f"{attrition_pct:.1f}%")
c4.metric("Avg Salary",      f"₹{avg_salary:,.0f}")

c5, c6, c7, c8 = st.columns(4)
c5.metric("Active Workforce", f"{int(hc_dept['active'].sum()):,}")
c6.metric("Attrited",         f"{total_attrited:,}")
c7.metric("Countries",        f"{total_countries}")
c8.metric("Total Payroll",    f"₹{total_payroll:,.0f}")

st.divider()

# ── Quick visuals ───────────────────────────────────────────────────────
left, right = st.columns(2)

with left:
    st.subheader("Headcount by Department")
    df = hc_dept.sort_values("headcount", ascending=False)
    st.plotly_chart(
        bar(df, x="department", y="headcount", color="department"),
        use_container_width=True,
    )

with right:
    st.subheader("Top-Paying Departments")
    if have_data(top_paying):
        st.plotly_chart(
            bar(top_paying, x="department", y="avg_salary",
                color="department",
                text_format="₹%{y:,.0f}"),
            use_container_width=True,
        )
    else:
        st.info("`salary/top_paying_depts` mart not found.")

st.subheader("Hiring Trend")
if have_data(hiring):
    df = hiring.copy()
    if "year_month" not in df.columns:
        df["year_month"] = (
            df["hire_year"].astype(str).str.zfill(4) + "-"
            + df["hire_month"].astype(str).str.zfill(2)
        )
    st.plotly_chart(
        line(df, x="year_month", y="hires"),
        use_container_width=True,
    )
else:
    st.info("`workforce/hiring_trends` mart not found.")

st.caption(
    "Built on the Medallion pipeline: Kafka -> Bronze -> Silver -> Gold -> "
    "this dashboard. Pages on the left drill into each domain."
)
