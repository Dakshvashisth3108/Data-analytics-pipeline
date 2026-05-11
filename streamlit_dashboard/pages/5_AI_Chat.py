"""AI Chat — conversational analytics over the HCM Gold marts.

Routes every question through ``router.HybridRouter``: intent classifier
decides SQL vs RAG vs both, results are synthesised by Gemma 2B via
Ollama into a natural-language answer, and rendered here with auto-
selected charts, the raw SQL, the RAG sources, and an inline trace.
"""
from __future__ import annotations

import time
from typing import Any

import streamlit as st

from components import _bootstrap  # noqa: F401  -- sys.path
from components.chat_render import (
    intent_badge,
    latency_badge,
    render_assistant_message,
    render_user_message,
)
from components.router_singleton import (
    SystemStatus,
    check_status,
    get_router,
    render_status_strip,
    reset_router_conversation,
)
from components.theme import apply_theme
from utils import get_logger

apply_theme(title="HCM — AI Chat", icon=":speech_balloon:")
LOG = get_logger("hcm.dashboard.chat")

st.title("Conversational Analytics")
st.caption(
    "Ask anything about your workforce in plain English. "
    "Hybrid router decides SQL vs semantic retrieval; Gemma 2B writes the answer."
)

# ── boot router (cached) + status strip ─────────────────────────────────
status: SystemStatus = check_status()
render_status_strip(status)

if not status.gold_present or not status.sql_ready:
    st.warning(
        "Gold parquet marts are missing. Run the pipeline first:\n\n"
        "```powershell\n"
        ". .\\scripts\\spark-env.ps1\n"
        "python -m producer.csv_to_kafka --max-records 1000 --no-loop --delay 0\n"
        "python -m bronze.ingest_employee_stream --once\n"
        "python -m silver.silver_etl\n"
        "python -m gold.gold_etl\n"
        "```"
    )
if not status.rag_ready:
    st.info(
        "RAG index is empty — semantic & hybrid questions will degrade to "
        "SQL-only. Build the index with:\n\n"
        "```powershell\npython -m embeddings.build_index\n```"
    )
if not status.ollama_ok:
    st.info(
        "Ollama isn't reachable — classification falls back to rules and "
        "answer synthesis uses a deterministic template. Start it with "
        "`ollama serve` and `ollama pull gemma2:2b`."
    )

st.divider()

# ── sidebar controls ────────────────────────────────────────────────────
EXAMPLES = [
    "Which department has the highest attrition rate?",
    "Show me the top 5 paying departments.",
    "How many employees joined in 2024?",
    "Tell me about our overall workforce health.",
    "Why is Marketing attrition so high?",
    "What's driving turnover in our top-paying departments?",
    "Compare performance ratings across departments.",
    "Which countries have the largest headcount?",
]

st.sidebar.header("Ask one of these")
for i, ex in enumerate(EXAMPLES):
    if st.sidebar.button(ex, key=f"ex_{i}", use_container_width=True):
        st.session_state["__pending_question__"] = ex

st.sidebar.divider()
st.sidebar.header("Session")
if st.sidebar.button("🧹  Clear conversation", use_container_width=True):
    st.session_state.messages = []
    reset_router_conversation()
    st.rerun()

if st.sidebar.button(
    "🔄  Reload router (pick up code changes)",
    use_container_width=True,
    help="Drops the cached HybridRouter so newly edited code is picked up "
         "without restarting Streamlit."
):
    st.session_state.messages = []
    get_router.clear()                # invalidates @st.cache_resource
    st.rerun()

st.sidebar.checkbox(
    "Show traces by default", value=False,
    key="show_traces",
    help="Trace tab is always available; this just expands it for new replies.",
)

# ── chat state ──────────────────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []  # list[dict] with role/content/response

# Replay history
for msg in st.session_state.messages:
    if msg["role"] == "user":
        render_user_message(msg["content"])
    else:
        render_assistant_message(msg["response"])


# ── handler ─────────────────────────────────────────────────────────────
def _handle_question(question: str) -> None:
    question = (question or "").strip()
    if not question:
        return

    # User echo
    render_user_message(question)
    st.session_state.messages.append({"role": "user", "content": question})

    router = get_router()

    # Spinner with intent preview after classification completes
    with st.chat_message("assistant"):
        placeholder = st.empty()
        placeholder.markdown("_Routing…_")

        t0 = time.perf_counter()
        try:
            resp = router.ask(question)
        except Exception as exc:
            LOG.exception("router_ask_failed")
            placeholder.error(f"Sorry — something went wrong: {exc}")
            st.session_state.messages.append({
                "role": "assistant",
                "content": f"(error) {exc}",
                "response": {
                    "answer_text": f"(error) {exc}",
                    "intent": "OFFTOPIC",
                    "intent_confidence": 0.0,
                    "intent_source": "fallback",
                    "elapsed_ms_total": int((time.perf_counter() - t0) * 1000),
                    "error": str(exc),
                },
            })
            return
        placeholder.empty()

    resp_dict = resp.to_dict()
    render_assistant_message(resp_dict)
    st.session_state.messages.append({
        "role": "assistant",
        "content": resp.answer_text,
        "response": resp_dict,
    })


# ── input bar ───────────────────────────────────────────────────────────
pending = st.session_state.pop("__pending_question__", None)
if pending:
    _handle_question(pending)

if prompt := st.chat_input(
    "Ask anything about workforce, attrition, salary, performance…"
):
    _handle_question(prompt)

# ── footer ──────────────────────────────────────────────────────────────
if st.session_state.messages:
    n_user = sum(1 for m in st.session_state.messages if m["role"] == "user")
    total_ms = sum(
        int(m.get("response", {}).get("elapsed_ms_total", 0))
        for m in st.session_state.messages if m["role"] == "assistant"
    )
    st.caption(
        f"{n_user} question(s) this session · cumulative router time "
        f"{total_ms/1000:.1f}s"
    )
