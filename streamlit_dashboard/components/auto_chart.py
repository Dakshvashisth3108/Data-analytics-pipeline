"""Heuristic chart selection for SQL result DataFrames.

We don't try to be clever — just pick the chart that's most likely to
illuminate the rows the user actually got back. The rules are:

  | shape                                          | chart       |
  |------------------------------------------------|-------------|
  | 1 categorical + 1 numeric (<= ~25 rows)        | bar         |
  | 1 categorical + 1 numeric (> 25 rows)          | horizontal  |
  | 1 date/year + 1 numeric                        | line        |
  | 1 categorical + 1 numeric + 1 "color" category | grouped bar |
  | 2 numerics + optional category                 | scatter     |
  | otherwise                                      | None (table)|

The caller renders the table either way; the chart is bonus.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from components.theme import PLOTLY_DISCRETE


@dataclass
class ChartChoice:
    kind: str             # "bar", "hbar", "line", "scatter", "grouped_bar"
    x: str
    y: str
    color: str | None = None
    reason: str = ""


def _is_date_like(s: pd.Series) -> bool:
    if pd.api.types.is_datetime64_any_dtype(s):
        return True
    name = (s.name or "").lower()
    return any(k in name for k in (
        "date", "year", "month", "hire_year", "snapshot_date", "year_month",
    ))


def _is_numeric(s: pd.Series) -> bool:
    return pd.api.types.is_numeric_dtype(s)


def _is_categorical(s: pd.Series) -> bool:
    return not _is_numeric(s) and not _is_date_like(s)


def pick_chart(df: pd.DataFrame) -> ChartChoice | None:
    if df is None or df.empty:
        return None
    cols = list(df.columns)
    cats = [c for c in cols if _is_categorical(df[c])]
    nums = [c for c in cols if _is_numeric(df[c])]
    dates = [c for c in cols if _is_date_like(df[c])]

    # Drop ID-like columns from candidates (single-value or all-unique strings)
    nums = [c for c in nums if df[c].nunique() > 1]

    if dates and nums:
        return ChartChoice(
            kind="line", x=dates[0], y=nums[0],
            color=cats[0] if cats else None,
            reason="date/year + numeric -> line",
        )

    if len(cats) >= 1 and len(nums) == 1:
        n = len(df)
        if len(cats) >= 2 and df[cats[1]].nunique() <= 8 and df[cats[1]].nunique() > 1:
            return ChartChoice(
                kind="grouped_bar", x=cats[0], y=nums[0], color=cats[1],
                reason="cat + cat + numeric -> grouped bar",
            )
        if n > 25:
            return ChartChoice(
                kind="hbar", x=nums[0], y=cats[0],
                reason=f"{n} rows -> horizontal bar for readability",
            )
        return ChartChoice(
            kind="bar", x=cats[0], y=nums[0],
            reason="cat + numeric -> bar",
        )

    if len(nums) >= 2 and len(cats) >= 1:
        return ChartChoice(
            kind="scatter", x=nums[0], y=nums[1],
            color=cats[0],
            reason="2 numerics + cat -> scatter",
        )

    if len(nums) >= 2:
        return ChartChoice(
            kind="scatter", x=nums[0], y=nums[1],
            reason="2 numerics -> scatter",
        )

    return None


def build_figure(df: pd.DataFrame, choice: ChartChoice) -> go.Figure:
    """Build the actual Plotly figure for a ChartChoice."""
    common = dict(color_discrete_sequence=PLOTLY_DISCRETE)
    if choice.kind == "bar":
        fig = px.bar(df, x=choice.x, y=choice.y, color=choice.color, **common)
    elif choice.kind == "hbar":
        df2 = df.sort_values(choice.x, ascending=True)
        fig = px.bar(df2, x=choice.x, y=choice.y, orientation="h", **common)
    elif choice.kind == "grouped_bar":
        fig = px.bar(df, x=choice.x, y=choice.y, color=choice.color,
                     barmode="group", **common)
    elif choice.kind == "line":
        fig = px.line(df, x=choice.x, y=choice.y, color=choice.color,
                      markers=True, **common)
    elif choice.kind == "scatter":
        fig = px.scatter(df, x=choice.x, y=choice.y, color=choice.color, **common)
    else:  # fallback
        fig = px.bar(df, x=choice.x, y=choice.y, **common)

    fig.update_layout(
        margin=dict(l=10, r=10, t=30, b=10),
        plot_bgcolor="white",
        font=dict(family="Inter, system-ui, -apple-system, sans-serif",
                  color="#102a43", size=13),
        legend_title_text="",
    )
    fig.update_xaxes(showgrid=False, zeroline=False)
    fig.update_yaxes(gridcolor="#e3e8ef", zeroline=False)
    return fig
