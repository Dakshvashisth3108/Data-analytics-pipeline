"""Performance Analytics page."""
from __future__ import annotations

import streamlit as st

from streamlit_dashboard.components import _bootstrap  # noqa: F401
from streamlit_dashboard.components.charts import bar, scatter
from streamlit_dashboard.components.data_loader import (
    empty_state, have_data, load_gold,
)
from streamlit_dashboard.components.filters import (
    apply_dimension_filter, department_filter,
)
from streamlit_dashboard.components.theme import apply_theme

apply_theme(title="HCM — Performance")
st.title("Performance Analytics")
st.caption("Ratings, top teams, and pay-for-performance signal.")

perf_dept   = load_gold("performance", "by_department")
top_teams   = load_gold("performance", "top_teams")
perf_salary = load_gold("performance", "vs_salary")

if not have_data(perf_dept):
    empty_state()
    st.stop()

# ── Sidebar filters ─────────────────────────────────────────────────────
st.sidebar.header("Filters")
dept_sel = department_filter(perf_dept)
perf_dept_f = apply_dimension_filter(perf_dept, "department", dept_sel)

# ── KPIs ────────────────────────────────────────────────────────────────
total_rated = int(perf_dept_f["rated_employees"].sum()) if not perf_dept_f.empty else 0
weighted_avg = (
    (perf_dept_f["avg_rating"] * perf_dept_f["rated_employees"]).sum()
    / perf_dept_f["rated_employees"].sum()
    if total_rated else 0.0
)
total_high = int(perf_dept_f["high_performers"].sum()) if not perf_dept_f.empty else 0
high_pct = (total_high / total_rated * 100) if total_rated else 0.0
top_dept = (
    perf_dept_f.sort_values("avg_rating", ascending=False).iloc[0]
    if not perf_dept_f.empty else None
)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Rated Employees", f"{total_rated:,}")
c2.metric("Avg Rating",      f"{weighted_avg:.2f}/5")
c3.metric("High Performers", f"{total_high:,}", delta=f"{high_pct:.1f}%")
if top_dept is not None:
    c4.metric("Top Dept", f"{top_dept['department']}",
              delta=f"{top_dept['avg_rating']:.2f}")

st.divider()

# ── Avg rating by dept ─────────────────────────────────────────────────
st.subheader("Average Rating by Department")
df = perf_dept_f.sort_values("avg_rating", ascending=False)
fig = bar(df, x="department", y="avg_rating", color="department",
          text_format="%{y:.2f}")
fig.update_yaxes(range=[0, 5])
st.plotly_chart(fig, use_container_width=True)

# ── Top teams + perf vs salary ─────────────────────────────────────────
left, right = st.columns(2)
with left:
    st.subheader("Top-Performing Teams")
    if have_data(top_teams):
        st.dataframe(
            top_teams[["rank", "department", "avg_rating",
                       "rated_employees", "high_performer_pct"]],
            use_container_width=True,
        )
    else:
        st.info("`performance/top_teams` mart not found.")

with right:
    st.subheader("Performance vs. Salary")
    if have_data(perf_salary):
        st.plotly_chart(
            scatter(perf_salary,
                    x="performance_rating", y="avg_salary",
                    size="employees",
                    hover=["employees", "median_salary"]),
            use_container_width=True,
        )
        st.caption(
            "Bubble size = number of employees at that rating. "
            "Look for a positive slope = pay scales with performance."
        )
    else:
        st.info("`performance/vs_salary` mart not found.")

with st.expander("Raw mart: performance/by_department"):
    st.dataframe(perf_dept_f, use_container_width=True)
