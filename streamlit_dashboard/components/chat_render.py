"""Render helpers for the AI chat page.

Kept separate from the page itself so the rendering logic is unit-testable
and reusable from any other surface (e.g. a future API/Slack/Discord
front-end could reuse ``intent_badge``, ``render_sql_block`` etc.).
"""
from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from components.auto_chart import build_figure, pick_chart

# Friendly intent labels + colours (matches theme.PALETTE)
_INTENT_STYLE = {
    "ANALYTICAL": ("🔢", "#0f4c81", "Analytical"),
    "SEMANTIC":   ("📚", "#3aa9ff", "Semantic"),
    "HYBRID":     ("🧩", "#22a06b", "Hybrid"),
    "OFFTOPIC":   ("🚫", "#8a99a8", "Off-topic"),
}


def intent_badge(intent: str, confidence: float | None = None,
                 source: str | None = None) -> str:
    """Return an inline HTML pill for the intent."""
    icon, color, label = _INTENT_STYLE.get(intent, ("•", "#8a99a8", intent))
    conf = f" · {confidence:.0%}" if confidence is not None else ""
    src = f" · via {source}" if source else ""
    return (
        f"<span style='background:{color}1a;color:{color};"
        f"border:1px solid {color}33;border-radius:999px;"
        f"padding:2px 10px;font-size:12px;font-weight:600;'>"
        f"{icon} {label}{conf}{src}</span>"
    )


def latency_badge(ms: int) -> str:
    color = "#22a06b" if ms < 500 else ("#f5a623" if ms < 2000 else "#d64545")
    return (
        f"<span style='background:{color}1a;color:{color};"
        f"border:1px solid {color}33;border-radius:999px;"
        f"padding:2px 10px;font-size:12px;font-weight:600;'>"
        f"⏱ {ms} ms</span>"
    )


def render_user_message(content: str) -> None:
    with st.chat_message("user"):
        st.markdown(content)


def render_assistant_message(response: dict[str, Any]) -> None:
    """Render a full assistant message including all detail tabs."""
    with st.chat_message("assistant"):
        # Header: badges
        meta_html = (
            intent_badge(response.get("intent", ""),
                         response.get("intent_confidence"),
                         response.get("intent_source"))
            + " &nbsp; "
            + latency_badge(int(response.get("elapsed_ms_total", 0)))
        )
        st.markdown(meta_html, unsafe_allow_html=True)

        # Main answer
        answer = response.get("answer_text") or "(empty answer)"
        st.markdown(answer)

        if response.get("error"):
            st.error(response["error"])

        # Detail tabs — show SQL whenever any SQL was generated (even if
        # it returned 0 rows), so the user can debug what the LLM did.
        has_sql_data = bool(response.get("sql_rows"))
        has_any_sql = bool(response.get("sql")) or bool(response.get("sql_raw_model_output"))
        has_rag = bool(response.get("rag_chunks"))
        has_trace = bool(response.get("intent"))

        tab_labels: list[str] = []
        if has_sql_data:
            tab_labels.append("📊 Chart")
        if has_any_sql:
            tab_labels.append("🗒 SQL")
        if has_rag:
            tab_labels.append("📚 Sources")
        if has_trace:
            tab_labels.append("🔬 Trace")

        if not tab_labels:
            return

        tabs = st.tabs(tab_labels)
        idx = 0

        if has_sql_data:
            with tabs[idx]:
                _render_chart_tab(response)
            idx += 1
        if has_any_sql:
            with tabs[idx]:
                _render_sql_tab(response)
            idx += 1
        if has_rag:
            with tabs[idx]:
                _render_sources_tab(response)
            idx += 1
        if has_trace:
            with tabs[idx]:
                _render_trace_tab(response)


# ── tab renderers ────────────────────────────────────────────────────────
def _render_chart_tab(response: dict) -> None:
    rows = response.get("sql_rows") or []
    cols = response.get("sql_columns") or []
    if not rows:
        st.info("No rows to chart.")
        return
    df = pd.DataFrame(rows, columns=cols or None)
    choice = pick_chart(df)
    if choice is None:
        st.info("This result shape doesn't fit a chart cleanly — see the SQL tab.")
        return
    fig = build_figure(df, choice)
    st.plotly_chart(fig, use_container_width=True)
    st.caption(f"Auto-selected: {choice.kind} ({choice.reason})")


def _render_sql_tab(response: dict) -> None:
    sql = response.get("sql")
    if sql:
        st.code(sql, language="sql")
    else:
        st.info("No SQL was generated. The model may have declined or errored.")

    cols = response.get("sql_columns") or []
    rows = response.get("sql_rows") or []
    total = response.get("sql_row_count", len(rows))
    if rows:
        df = pd.DataFrame(rows, columns=cols or None)
        st.dataframe(df, use_container_width=True)
        if total > len(rows):
            st.caption(f"Showing {len(rows)} of {total} rows.")
    elif sql:
        st.warning(
            "SQL ran successfully but returned 0 rows. "
            "The model likely picked the wrong table or filter — "
            "try rephrasing or check the schema below."
        )

    tables = response.get("sources", []) or []
    sql_tables = [t for t in tables if not t.count(".")]
    if sql_tables:
        st.caption("Tables: " + ", ".join(sql_tables))

    sql_err = response.get("sql_error")
    if sql_err:
        st.error(f"SQL stage error: {sql_err}")


def _render_sources_tab(response: dict) -> None:
    chunks = response.get("rag_chunks") or []
    if not chunks:
        st.info("No semantic context was used.")
        return
    for c in chunks:
        meta = c.get("metadata") or {}
        domain = meta.get("domain", "?")
        sim = c.get("similarity", 0.0)
        with st.expander(f"{c.get('chunk_id', '?')}  ·  {domain}  ·  sim={sim:.2f}"):
            st.markdown(c.get("text") or "")
            if meta:
                # Pretty-print scalar metadata only
                clean = {k: v for k, v in meta.items()
                         if isinstance(v, (str, int, float, bool))}
                if clean:
                    st.json(clean)


def _render_trace_tab(response: dict) -> None:
    c1, c2, c3 = st.columns(3)
    c1.metric("Intent", response.get("intent", "-"))
    conf = response.get("intent_confidence")
    c2.metric("Confidence", f"{conf:.0%}" if isinstance(conf, (int, float)) else "-")
    c3.metric("Routed via", response.get("intent_source", "-"))

    reason = response.get("intent_reason")
    if reason:
        st.markdown(f"**Reason:** {reason}")

    # Timing breakdown
    t = {
        "classify": response.get("elapsed_ms_classify", 0),
        "sql":      response.get("elapsed_ms_sql", 0),
        "rag":      response.get("elapsed_ms_rag", 0),
        "synth":    response.get("elapsed_ms_synth", 0),
        "total":    response.get("elapsed_ms_total", 0),
    }
    timing_df = pd.DataFrame([t])
    st.dataframe(timing_df, hide_index=True, use_container_width=True)

    # Raw LLM output (debugging Gemma's SQL generation)
    raw = response.get("sql_raw_model_output")
    if raw:
        with st.expander("Raw LLM output (SQL stage)"):
            st.code(raw, language="markdown")
