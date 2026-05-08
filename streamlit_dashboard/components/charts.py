"""Reusable Plotly chart builders. Each helper returns a Figure that
the caller renders with ``st.plotly_chart(fig, use_container_width=True)``.
"""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from components.theme import PALETTE, PLOTLY_DISCRETE


def _layout(fig: go.Figure, *, title: str | None = None,
            margin_t: int = 50) -> go.Figure:
    fig.update_layout(
        title=title,
        margin=dict(l=10, r=10, t=margin_t, b=10),
        plot_bgcolor="white",
        font=dict(family="Inter, system-ui, -apple-system, sans-serif",
                  color="#102a43", size=13),
        colorway=PLOTLY_DISCRETE,
    )
    fig.update_xaxes(showgrid=False, zeroline=False)
    fig.update_yaxes(gridcolor="#e3e8ef", zeroline=False)
    return fig


def bar(df: pd.DataFrame, *, x: str, y: str, color: str | None = None,
        title: str | None = None, orientation: str = "v",
        text_format: str | None = None) -> go.Figure:
    fig = px.bar(df, x=x, y=y, color=color, orientation=orientation)
    if text_format:
        fig.update_traces(texttemplate=text_format, textposition="outside")
    return _layout(fig, title=title)


def horizontal_bar(df: pd.DataFrame, *, category: str, value: str,
                   title: str | None = None,
                   color: str | None = None) -> go.Figure:
    df = df.sort_values(value, ascending=True)
    fig = px.bar(df, x=value, y=category, color=color, orientation="h")
    return _layout(fig, title=title)


def line(df: pd.DataFrame, *, x: str, y: str,
         color: str | None = None, title: str | None = None,
         markers: bool = True) -> go.Figure:
    fig = px.line(df, x=x, y=y, color=color, markers=markers)
    fig.update_traces(line=dict(width=2.5))
    return _layout(fig, title=title)


def scatter(df: pd.DataFrame, *, x: str, y: str,
            size: str | None = None, color: str | None = None,
            hover: list[str] | None = None,
            title: str | None = None) -> go.Figure:
    fig = px.scatter(df, x=x, y=y, size=size, color=color,
                     hover_data=hover, size_max=40)
    return _layout(fig, title=title)


def donut(df: pd.DataFrame, *, names: str, values: str,
          title: str | None = None) -> go.Figure:
    fig = px.pie(df, names=names, values=values, hole=0.55)
    fig.update_traces(textposition="outside",
                      texttemplate="%{label} %{percent}")
    return _layout(fig, title=title)
