"""Cached HybridRouter for the Streamlit session + boot-time health checks.

The router holds expensive resources (Spark-free, but still: a DuckDB
connection with 14 views mounted, a ChromaDB persistent client, and a
sentence-transformer model loaded into memory). We build it ONCE per
Streamlit process via ``@st.cache_resource`` so navigating between
pages doesn't pay the init cost every time.

Conversation memory lives on the router (rolling 6 turns) and survives
page navigation as long as the cached router is alive. Reset via
``reset_router_conversation()``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import streamlit as st

from utils import get_logger, load_config

LOG = get_logger("hcm.dashboard.router")


@dataclass
class SystemStatus:
    ollama_ok: bool
    ollama_msg: str
    rag_ready: bool
    rag_count: int
    sql_ready: bool
    sql_tables: int
    gold_present: bool


@st.cache_resource(show_spinner="Booting analytics router...")
def get_router():
    """Build and cache the HybridRouter for this Streamlit session."""
    from router.router import build_default_router
    router = build_default_router()
    LOG.info("dashboard_router_ready sql_tables=%s",
             len(router.sql_engine.catalog.tables) if router.sql_engine else 0)
    return router


def reset_router_conversation() -> None:
    """Drop the cached router's conversation history."""
    try:
        get_router().reset_conversation()
    except Exception:
        LOG.exception("reset_conversation_failed")


def check_status() -> SystemStatus:
    """Run lightweight health checks against each subsystem. Never raises."""
    router = get_router()

    # SQL engine
    sql_ready, sql_tables = False, 0
    if router.sql_engine is not None:
        try:
            sql_tables = len(router.sql_engine.catalog.tables)
            sql_ready = sql_tables > 0
        except Exception:
            sql_ready = False

    # Gold parquet on disk
    from pathlib import Path

    from utils import gold_path
    gold_present = Path(gold_path("")).exists()

    # RAG index
    rag_ready, rag_count = False, 0
    if router.retriever is not None:
        try:
            rag_count = router.retriever.store.count() if router.retriever.store else 0
            rag_ready = rag_count > 0
        except Exception:
            rag_ready = False

    # Ollama
    ollama_ok, ollama_msg = False, "no client"
    try:
        client = (
            router.synthesizer.ollama
            if router.synthesizer and router.synthesizer.ollama
            else (router.classifier.ollama if router.classifier else None)
        )
        if client is not None:
            client.healthcheck()
            ollama_ok = True
            ollama_msg = f"reachable ({client.model})"
    except Exception as exc:
        ollama_msg = str(exc)[:140]

    return SystemStatus(
        ollama_ok=ollama_ok, ollama_msg=ollama_msg,
        rag_ready=rag_ready, rag_count=rag_count,
        sql_ready=sql_ready, sql_tables=sql_tables,
        gold_present=gold_present,
    )


def render_status_strip(status: SystemStatus) -> None:
    """Render a compact one-line system-status indicator at the top."""
    cols = st.columns(4)

    def _pill(col, label: str, ok: bool, detail: str = "") -> None:
        with col:
            mark = ":green_circle:" if ok else ":red_circle:"
            st.markdown(f"{mark} **{label}**  \n<span style='color:#5b6b7d;font-size:12px'>{detail}</span>",
                        unsafe_allow_html=True)

    _pill(cols[0], "Ollama (LLM)", status.ollama_ok, status.ollama_msg)
    _pill(cols[1], "SQL engine",  status.sql_ready,
          f"{status.sql_tables} Gold views" if status.sql_ready else "no views")
    _pill(cols[2], "RAG index",   status.rag_ready,
          f"{status.rag_count} chunks" if status.rag_ready else "empty (run embeddings.build_index)")
    _pill(cols[3], "Gold parquet", status.gold_present,
          "data/gold" if status.gold_present else "missing (run gold_etl)")
