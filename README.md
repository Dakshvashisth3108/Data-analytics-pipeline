# HCM Analytics — End-to-End AI Workforce Platform

A production-grade Human Capital Management analytics platform that streams employee data through a Kafka-fed Medallion lakehouse, serves it as 14 pre-aggregated Gold marts, and exposes it through a **conversational AI interface** that combines precise SQL execution with semantic vector search.

```
Raw CSV → Kafka → Bronze → Silver → Gold ─┬─ Streamlit dashboards (Plotly)
                                          ├─ ChromaDB vector index (RAG)
                                          ├─ NL→SQL engine (DuckDB)
                                          └─ Hybrid router (Gemma 2B intent + synth)
                                                                  │
                                                                  ▼
                                                       AI Chat page (Streamlit)
```

Ask in plain English — *"Which country has the highest attrition?"* — and the platform classifies the intent, routes to SQL or RAG (or both), validates the generated SQL for safety, executes it, and writes a natural-language answer back with citations.

---

## Table of contents

1. [What's inside](#whats-inside)
2. [Architecture at a glance](#architecture-at-a-glance)
3. [How a chat question flows](#how-a-chat-question-flows)
4. [Prerequisites](#prerequisites)
5. [Quickstart](#quickstart)
6. [Project layout](#project-layout)
7. [Each subsystem in depth](#each-subsystem-in-depth)
8. [Configuration](#configuration)
9. [Production-grade design points](#production-grade-design-points)
10. [Cloud deployment hints](#cloud-deployment-hints)

---

## What's inside

| Capability | Where |
|---|---|
| **Synthetic data generator** with realistic dirty values | `scripts/generate_hcm_dataset.py` |
| **Kafka producer** streaming CSV → JSON events | `producer/csv_to_kafka.py` |
| **Bronze ingest** (Spark Structured Streaming, Kafka → Parquet) | `bronze/ingest_employee_stream.py` |
| **Silver ETL** (cleaning, dedupe, DQ gates) | `silver/silver_etl.py` |
| **Gold marts** (14 pre-aggregated business analytics tables) | `gold/gold_etl.py` |
| **BI dashboard** (5 pages: Overview, Workforce, Salary, Attrition, Performance) | `streamlit_dashboard/app.py` + `pages/` |
| **RAG embedding pipeline** (Gold marts → 138 business-insight chunks → ChromaDB) | `embeddings/build_index.py` |
| **NL→SQL engine** (Gemma 2B + sqlglot validator + DuckDB on parquet) | `nl2sql/ask.py` |
| **Hybrid router** (intent classifier + SQL/RAG dispatch + LLM synthesis) | `router/chat.py` |
| **AI Chat page** (Streamlit conversational UI) | `streamlit_dashboard/pages/5_AI_Chat.py` |

---

## Architecture at a glance

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ DATA PIPELINE                                                                │
│                                                                              │
│  scripts/generate_hcm_dataset.py                                             │
│         │     10k rows, with dirty values: "$50,000", "31/02/2024", etc.     │
│         ▼                                                                    │
│   data/raw/hcm_employees.csv  hcm_employees.json  hcm_employees.parquet      │
│         │                                                                    │
│         │ producer/csv_to_kafka.py  (confluent-kafka)                        │
│         ▼                                                                    │
│   ┌─────────────────────────────────────┐                                    │
│   │  Kafka (Docker)                     │                                    │
│   │  topic: hcm_employee_data           │                                    │
│   └─────────────────────────────────────┘                                    │
│         │ bronze/ingest_employee_stream.py  (Spark Structured Streaming)     │
│         ▼                                                                    │
│   data/bronze/employees/  (Parquet, partitioned by ingest_date)              │
│         │ silver/silver_etl.py  (PySpark batch)                              │
│         ▼                                                                    │
│   data/silver/dim_employee/  (cleaned, deduped, validated)                   │
│         │ gold/gold_etl.py  (PySpark batch)                                  │
│         ▼                                                                    │
│   data/gold/                                                                 │
│     ├─ attrition/    {by_department, by_country, trend_by_cohort, by_tenure} │
│     ├─ salary/       {by_department, top_paying_depts, distribution}         │
│     ├─ workforce/    {by_department, by_country, exp_dist, hiring_trends}    │
│     └─ performance/  {by_department, top_teams, vs_salary}                   │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
              │                       │                       │
              ▼                       ▼                       ▼
┌──────────────────────┐  ┌──────────────────────┐  ┌──────────────────────┐
│ BI DASHBOARD         │  │ RAG INDEX            │  │ NL→SQL ENGINE        │
│                      │  │                      │  │                      │
│ pandas + plotly      │  │ embeddings/          │  │ nl2sql/              │
│ streamlit_dashboard/ │  │   build_index.py     │  │   schema_introspect  │
│   pages/1..4         │  │ chunkers/ -> 138     │  │   prompts (few-shot) │
│                      │  │   chunks             │  │   ollama_client      │
│ Reads Gold parquet   │  │ sentence-transformers│  │   sql_validator      │
│ directly with        │  │   /all-MiniLM-L6-v2  │  │   sql_repair         │
│ pandas; no JVM.      │  │ Persisted to         │  │   duckdb_runner      │
│                      │  │   data/vectors/      │  │                      │
│                      │  │   chroma/            │  │ 14 read-only DuckDB  │
│                      │  │                      │  │ views over Gold      │
└──────────────────────┘  └──────────────────────┘  └──────────────────────┘
              │                       │                       │
              │                       │                       │
              │             ┌─────────┴───────────────────────┘
              │             │
              │             ▼
              │   ┌─────────────────────────────────────────────────────────┐
              │   │ HYBRID ROUTER (router/)                                 │
              │   │                                                         │
              │   │   intent.py        Intent enum {ANALYTICAL, SEMANTIC,   │
              │   │                                 HYBRID, OFFTOPIC}       │
              │   │   classifier.py    Two-tier (rules + Gemma 2B fallback) │
              │   │   rag_retriever.py wraps ChromaDB                       │
              │   │   conversation.py  rolling 6-turn memory                │
              │   │   synthesizer.py   Gemma 2B answer composer             │
              │   │   router.py        HybridRouter.ask() orchestrator      │
              │   └─────────────────────────────────────────────────────────┘
              │             │
              ▼             ▼
   ┌─────────────────────────────────────────────────────────────────────────┐
   │ AI CHAT PAGE (streamlit_dashboard/pages/5_AI_Chat.py)                   │
   │                                                                         │
   │  · st.chat_input + st.chat_message history                              │
   │  · Status pills: Ollama / SQL / RAG / Gold all green                    │
   │  · Per-reply tabs: Chart (auto-picked Plotly) / SQL / Sources / Trace   │
   │  · Sidebar: example questions, clear conversation, reload router        │
   │                                                                         │
   └─────────────────────────────────────────────────────────────────────────┘

                  ┌───────────────────────────────────────────┐
                  │ Local LLM via Ollama: gemma2:2b on :11434 │
                  └───────────────────────────────────────────┘
```

---

## How a chat question flows

A walkthrough of *"Why is Marketing attrition so high?"* — the hybrid case that exercises every layer.

```
1.  User types in st.chat_input
        │
        ▼
2.  router.IntentClassifier.classify(question, history)
        Tier 1 rules: "why is" → HYBRID (confidence 1.00, ~1 ms)
        │  needs_sql=True  needs_rag=True
        │
        ├─────────────────────────────┐
        ▼                             ▼
3.  nl2sql.NL2SQLEngine.ask()      4.  router.RagRetriever.retrieve()
                                          │
        a) Build schema-aware prompt           Embed question with MiniLM-L6-v2
           with 14 view definitions          │
           + 4 few-shot examples               Chroma cosine query, top-5
        │                                   │
        ▼                                   ▼
        b) Ollama → Gemma 2B               5 chunks: "Marketing attrition
           returns SQL                      31.4%, highest in the company..."
        │
        ▼
        c) sql_repair: fixes hallucinated
           "FROM attrition" -> "FROM
           attrition_by_department" via
           keyword scoring (deterministic,
           no LLM)
        │
        ▼
        d) sql_validator (sqlglot):
           - SELECT/WITH only
           - keyword denylist (DROP, ATTACH,
             COPY, INSTALL, LOAD, PRAGMA,...)
           - table allowlist (14 views)
           - reject schema-qualified refs
           - reject multi-statements
           - auto-inject LIMIT 500
        │
        ▼
        e) DuckDB executes read-only SQL
           on data/gold/*/*.parquet views
           → rows: [{department: Marketing,
                     attrition_rate: 0.314,
                     attrited: 11, ...}]
        │
        └─────────────────────────────┘
                      │
                      ▼
5.  router.AnswerSynthesizer.synthesize(intent=HYBRID, sql, chunks)
        System: "concise HR analyst, cite numbers, no hallucinations"
        User:   recent context (history)
              + SQL table (5 rows)
              + RAG chunk bullets (5)
              + "tie numbers and reasons together in 2-4 sentences"
        │
        ▼ Ollama → Gemma 2B writes the final answer
6.  Streamlit renders the assistant message:
        · Intent pill (HYBRID, 100%, via rule)
        · Latency pill (1,234 ms)
        · Markdown answer
        · Tabs: [Chart] [SQL] [Sources] [Trace]
        · Conversation.add(turn) — 1-line summary saved for next follow-up
```

### What happens for *"Hello"* (OFFTOPIC)
Rules fire `OFFTOPIC` at confidence 0.6 → **zero engines run, zero LLM calls**. The synthesizer returns a hard-coded scope reminder.

### What happens for *"Show me top 5 paying departments"* (ANALYTICAL)
SQL path only. RAG is skipped. ~80 ms SQL + ~600 ms LLM synthesis.

### What happens for *"Tell me about workforce health"* (SEMANTIC)
RAG path only. SQL is skipped. The synth LLM paraphrases retrieved chunks.

---

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| **Python** | 3.10+ (tested with 3.13) | |
| **Java** | **21 LTS** for Spark | Spark 4.x doesn't support Java 24+ yet. Installer at `scripts/setup_java21.ps1`. |
| **Hadoop winutils** | 3.3.6 (Windows only) | Installer at `scripts/setup_winutils.ps1`. |
| **Docker Desktop** | latest | For the Kafka + Zookeeper containers. |
| **Ollama** | latest | Local LLM runtime. Download from [ollama.com](https://ollama.com/download). |
| **Gemma 2B model** | gemma2:2b | `ollama pull gemma2:2b` (~1.5 GB quantised). |

---

## Quickstart

Open PowerShell in `C:\Users\DAKSH\Documents\hcm-analytics` (or wherever you cloned it).

### 1 · One-time Windows setup

```powershell
# Install Hadoop winutils (Spark needs this on Windows)
powershell -ExecutionPolicy Bypass -File scripts\setup_winutils.ps1

# Install Java 21 LTS for Spark (alongside your default Java)
powershell -ExecutionPolicy Bypass -File scripts\setup_java21.ps1

# Pull the local LLM
ollama pull gemma2:2b
```

> **Open a fresh terminal** after the setup scripts so the persistent `HADOOP_HOME` and `PATH` updates take effect.

### 2 · Python environment

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 3 · Generate synthetic data (or drop in your own CSV)

```powershell
python scripts\generate_hcm_dataset.py --rows 10000
```

Or replace `data/raw/hcm_employees.csv` with your own data — see [bring your own data](#bring-your-own-data) below.

### 4 · Start the streaming infra

```powershell
docker compose up -d                 # Kafka + Zookeeper
ollama serve                         # in a separate terminal
```

### 5 · Run the data pipeline (one-shot)

```powershell
# Switch this shell's JAVA_HOME to Java 21 for Spark
. .\scripts\spark-env.ps1

# Stream the CSV into Kafka
python -m producer.csv_to_kafka --max-records 1000 --no-loop --delay 0

# Bronze: Kafka -> raw Parquet (Spark Structured Streaming)
python -m bronze.ingest_employee_stream --once

# Silver: clean, dedupe, validate -> dim_employee
python -m silver.silver_etl

# Gold: 14 pre-aggregated business marts
python -m gold.gold_etl
```

### 6 · Build the RAG index

```powershell
python -m embeddings.build_index
```

Generates ~138 business-insight chunks from the Gold marts, embeds with MiniLM-L6-v2 (~80 MB model, downloaded on first run), and persists to `data/vectors/chroma/`.

### 7 · Launch the dashboard

```powershell
streamlit run streamlit_dashboard\app.py
```

Open [http://localhost:8501](http://localhost:8501). The **AI Chat** page is the 5th item in the sidebar.

---

## Project layout

```
hcm-analytics/
├── docker-compose.yml             Kafka + Zookeeper (single-broker)
├── docker/                        Optional full dev stack (Spark, Jupyter, etc.)
├── configs/
│   ├── app.yaml                   ALL knobs — kafka, lake, spark, embeddings, nl2sql, router
│   └── logging.yaml               Rotating JSON file + console
├── scripts/
│   ├── generate_hcm_dataset.py    Synthetic data factory
│   ├── setup_winutils.ps1         One-time Hadoop helper for Windows
│   ├── setup_java21.ps1           One-time Java 21 LTS install (Spark needs it)
│   └── spark-env.ps1              Per-shell JAVA_HOME switcher (auto-generated)
│
├── schemas/                       Single source of truth for event shapes
│   ├── hcm_schemas.py             Spark StructType for HCM_EMPLOYEE_CSV
│   └── employee.json              Avro mirror for schema-registry integration
│
├── producer/                      CSV → Kafka
│   ├── csv_to_kafka.py            Production-style confluent-kafka streamer
│   ├── generators.py              Faker-based synthetic event generators
│   ├── kafka_producer.py          HcmKafkaProducer wrapper (library)
│   └── run.py                     CLI for Faker-stream producer (alternative)
│
├── consumer/                      Audit + alias for the Bronze streaming consumer
│   ├── audit_consumer.py          Standalone Kafka tail (no Spark)
│   └── spark_streaming_consumer.py    alias → bronze.ingest_employee_stream
│
├── bronze/                        Kafka → raw Parquet (Spark Structured Streaming)
│   └── ingest_employee_stream.py  --once (availableNow) for backfill / CI
│
├── silver/                        Bronze → cleaned dim_employee
│   ├── transformations.py         Pure DataFrame→DataFrame cleaning functions
│   ├── data_quality.py            Configurable DQ checks (block on critical)
│   ├── build_silver_employees.py  Orchestrator
│   └── silver_etl.py              Friendly alias
│
├── gold/                          Silver → 14 business marts
│   ├── attrition.py               4 marts (by_dept, by_country, cohort, tenure)
│   ├── salary.py                  3 marts (by_dept, top_paying, distribution)
│   ├── workforce.py               4 marts (by_country, by_dept, exp_dist, hiring)
│   ├── performance.py             3 marts (by_dept, top_teams, vs_salary)
│   ├── validation.py              Output checks
│   ├── build_employee_gold.py     Orchestrator
│   └── gold_etl.py                Friendly alias
│
├── embeddings/                    Gold marts → ChromaDB (RAG)
│   ├── chunk.py                   Chunk dataclass + stable_id()
│   ├── embedder.py                sentence-transformers wrapper (lazy)
│   ├── vectorstore.py             ChromaDB persistent client wrapper
│   ├── build_index.py             CLI: build / reset / query
│   └── chunkers/
│       ├── _helpers.py            fmt_money, fmt_pct, load_mart, ...
│       ├── overview.py            5 cross-domain CEO-level chunks
│       ├── attrition.py           47 row + summary chunks across 4 marts
│       ├── salary.py              17 chunks across 3 marts
│       ├── workforce.py           47 chunks across 4 marts
│       └── performance.py         22 chunks across 3 marts
│
├── nl2sql/                        Question → SQL → rows
│   ├── ollama_client.py           HTTP wrapper with /api/version pre-flight
│   ├── schema_introspect.py       Parquet → SchemaCatalog → prompt doc
│   ├── prompts.py                 SYSTEM + few-shot examples + extractor
│   ├── sql_repair.py              Auto-fix bare table names ("attrition" →
│   │                                "attrition_by_country") via keyword scoring
│   ├── sql_validator.py           sqlglot allowlist (statements + keywords +
│   │                                tables) + auto-LIMIT injection
│   ├── duckdb_runner.py           in-memory read-only views over parquet
│   ├── engine.py                  NL2SQLEngine.ask() — top-level orchestrator
│   └── ask.py                     CLI: python -m nl2sql.ask "..."
│
├── router/                        Hybrid intent + SQL/RAG orchestration
│   ├── intent.py                  Intent enum + ClassificationResult
│   ├── classifier.py              Two-tier (~20 rules + Gemma 2B fallback)
│   ├── rag_retriever.py           Typed wrapper over ChromaStore
│   ├── conversation.py            Rolling 6-turn history (Q + 1-line summary)
│   ├── synthesizer.py             LLM answer composer (deterministic 0-row path)
│   ├── router.py                  HybridRouter.ask() — public API
│   └── chat.py                    REPL CLI: python -m router.chat
│
├── streamlit_dashboard/           Web UI (no JVM, just pandas)
│   ├── app.py                     Home — Executive Overview
│   ├── pages/
│   │   ├── 1_Workforce.py
│   │   ├── 2_Salary.py
│   │   ├── 3_Attrition.py
│   │   ├── 4_Performance.py
│   │   └── 5_AI_Chat.py           Conversational analytics
│   └── components/
│       ├── _bootstrap.py          sys.path setup
│       ├── theme.py               Palette, page config, KPI CSS
│       ├── data_loader.py         @st.cache_data parquet readers
│       ├── filters.py             Sidebar multi-selects (session-scoped)
│       ├── charts.py              Plotly bar/line/scatter/donut
│       ├── router_singleton.py    @st.cache_resource HybridRouter + health
│       ├── auto_chart.py          Heuristic chart-from-SQL picker
│       └── chat_render.py         Message renderers + intent/latency badges
│
├── tests/                         Pytest fixtures + schema round-trip tests
├── logs/                          Rotating JSON logs (gitignored)
├── data/                          Local lakehouse (gitignored)
│   ├── raw/                       CSV/JSON/Parquet input
│   ├── bronze/                    Raw Parquet (Kafka append)
│   ├── silver/                    Cleaned dim_employee
│   ├── gold/                      14 marts
│   ├── checkpoints/               Spark Structured Streaming bookmarks
│   └── vectors/chroma/            ChromaDB persistent store
│
├── notebooks/                     Exploratory Jupyter notebooks
├── .vscode/launch.json            One-click run configs for each stage
├── requirements.txt               Pinned Python deps (Python 3.13 compatible)
└── README.md                      ← you are here
```

---

## Each subsystem in depth

### 1 · Data pipeline (Bronze / Silver / Gold)

**Bronze** — `bronze/ingest_employee_stream.py`. Spark Structured Streaming reads the `hcm_employee_data` Kafka topic, parses each JSON message against the explicit `HCM_EMPLOYEE_CSV_SCHEMA`, augments with `ingest_ts` / `ingest_date` / Kafka offsets, and writes Parquet partitioned by date. **Permissive by design**: dirty fields like `salary="$5,358,375"` and `joining_date="31/02/2024"` are kept as strings; no row is dropped. `_raw` carries the original JSON for replay.

**Silver** — `silver/silver_etl.py`. Pure pandas-style PySpark transformations:
- Department normalisation: `"Engg."`, `"engineering"`, `"ENGG"` → all become `"Engineering"` (regex-based canonical map).
- Salary cleansing: `"$5,358,375"` → `5358375.0`; `"75k"` → `75000.0`; `"N/A"` → null.
- Date validation: ANSI-safe `try_to_date(yyyy-MM-dd)`; reject < 1950 and future dates.
- Deduplication: keep latest record per `employee_id` (by `ingest_ts`, then Kafka offset).
- Range validation: rating 1–5, experience 0–60.
- DQ gates: `--fail-on-dq` exits 6 if invalid_salary_pct > 10% or other configurable thresholds breach.

**Gold** — `gold/gold_etl.py`. Per-domain aggregation modules (`attrition.py`, `salary.py`, `workforce.py`, `performance.py`) each define multiple "marts". The orchestrator runs all 14, validates output structure, and writes Parquet to `data/gold/<domain>/<metric>/`. Output is **partitioned for fast incremental reads** (where applicable) and **coalesced to one file per mart** for snappy BI loads.

### 2 · Advanced RAG layer

The RAG pipeline (`embeddings/`) is what makes "Tell me about workforce health" answerable. It does **not** embed raw rows — that would lose business meaning. Instead, each Gold mart produces **narrative business-insight chunks**:

```
Per-mart strategy:
  ROW chunks    — one per significant dimension (e.g. one per department)
                  worded as a self-contained business statement
  SUMMARY chunk — synthesises the table (top/bottom, deltas, leaderboards)

Plus a cross-domain `overview` pack with 5 CEO-level chunks
  (company snapshot, attrition hotspots, compensation leaders,
   talent density, hiring pulse).

Total: ~138 chunks for the full 14-mart catalogue.
```

Example chunk text (auto-generated from real Gold data):

> *"In the Marketing department, total headcount is 35 employees, with 11 who have left and 24 still active. The attrition rate is 31.4%."*

> *"Across 8 departments, the overall attrition rate is 17.0%. The departments with the highest attrition are Marketing (31.4%), HR (28.2%), IT (21.4%). The departments with the lowest attrition are Engineering (12.5%)..."*

**Embedding model**: `sentence-transformers/all-MiniLM-L6-v2` (384 dims, ~80 MB, CPU-fast). Normalised so cosine similarity becomes a dot-product.

**Storage**: ChromaDB `PersistentClient` at `data/vectors/chroma/`. One collection (`hcm_insights`) with `hnsw:space=cosine`. **Stable IDs** like `attrition.by_department.dept=Engineering` so re-running the indexer upserts in place instead of duplicating.

**Metadata on every chunk** enables filtered retrieval — e.g. "show me only attrition insights from this week's snapshot":
```python
store.query("worst-attrition departments", embedder,
            n_results=5,
            where={"domain": "attrition", "kind": "summary"})
```

### 3 · NL→SQL engine

`nl2sql/` translates plain-English questions to validated DuckDB SQL over Gold parquet. The pipeline:

```
question
   │
   ▼
schema_introspect.SchemaCatalog        ← reads pyarrow schema from every Gold
   │                                     parquet file → builds a Markdown doc
   ▼                                     listing all 14 views + columns
prompts.build_user_prompt              ← schema + 4 few-shot examples +
   │                                     the user's question
   ▼
OllamaClient.generate                  ← Gemma 2B via /api/generate
   │
   ▼
prompts.extract_sql                    ← grabs the LAST fenced ```sql block
   │                                     (because few-shot makes the model
   ▼                                     echo example blocks before answering)
sql_repair.repair_bare_tables          ← deterministic fix for hallucinated
   │                                     "FROM attrition" → "FROM attrition_
   ▼                                     by_country" via keyword scoring
sql_validator.validate_sql             ← sqlglot AST checks:
   │                                       - SELECT/WITH only
   │                                       - keyword denylist
   │                                       - table allowlist
   │                                       - reject schema-qualified refs
   │                                       - reject multi-statements
   │                                       - auto-inject LIMIT
   ▼
duckdb_runner.execute                  ← in-memory DuckDB, autoinstall+
   │                                     autoload extensions disabled, one
   ▼                                     CREATE VIEW per Gold mart
AnswerResult (rows, sql, error, raw model output, timings)
```

**Safety guarantees** (all enforced by `sql_validator` + DuckDB config):

| Attack | How blocked |
|---|---|
| `DROP TABLE attrition_by_department` | Statement-kind allowlist rejects (`Drop` not in `{Select, With}`) |
| `SELECT * FROM read_parquet('C:/etc/passwd')` | sqlglot Table node has empty name → not in allowlist |
| `ATTACH 'remote.db'; SELECT 1` | Keyword denylist + multi-statement reject |
| `SELECT ...; DELETE FROM x` | Multi-statement reject |
| SQL > 4000 chars | Rejected before parse |
| Result set 1B rows | `fetchmany(max_result_rows)` hard cap |
| Extension loading | DuckDB `autoinstall_known_extensions=false` |

### 4 · Hybrid router

`router/` decides for each question which engines to invoke. Four mutually-exclusive intents:

| Intent | Triggers | Routes to |
|---|---|---|
| `ANALYTICAL` | "top N", "highest", "average", "how many" | SQL only |
| `SEMANTIC` | "tell me about", "overview", "summary" | RAG only |
| `HYBRID` | "why is", "what's driving", "explain" | Both, then synthesise |
| `OFFTOPIC` | "hello", "weather", non-HCM | Decline, no engines, no LLM |

**Two-tier classifier**:
- **Tier 1**: ~20 weighted regex rules. Fires in microseconds at zero LLM cost. Handles ~85% of questions clearly (top-N, why-is, tell-me-about, hello/weather, etc.).
- **Tier 2**: Gemma 2B classifier with conversation context. Only fires when Tier 1 confidence < 0.75. Handles ambiguous or follow-up questions.

**Conversation memory**: rolling 6-turn buffer stores just the question + a 1-line answer summary (e.g. `[SQL] department=Marketing, attrition_rate=0.314`). Used to resolve "why is *it* high?" follow-ups.

**Synthesizer**: intent-aware Gemma 2B prompt. Three deterministic short-circuits:
- OFFTOPIC → hard-coded scope reminder, zero LLM call
- ANALYTICAL + 0 rows → precise message tied to the actual SQL that ran, zero LLM call (prevents Gemma 2B from hallucinating "the data doesn't contain X")
- Ollama unreachable → deterministic template fallback

### 5 · AI Chat page

`streamlit_dashboard/pages/5_AI_Chat.py` wraps the HybridRouter in a chat UI:

- **Status strip** at top: four pills (Ollama, SQL engine, RAG, Gold) green/red with the exact CLI command to fix each missing piece.
- **Sidebar**: clickable example questions for each intent, "Clear conversation" (drops UI history + router memory), **"Reload router"** (invalidates `@st.cache_resource` so code edits take effect without restarting Streamlit).
- **Chat history** rendered via `st.chat_message` from `st.session_state.messages`.
- **Per-reply tabs**:
  - **Chart** — auto-picked Plotly figure (bar / horizontal bar / line / scatter / grouped bar based on SQL result shape)
  - **SQL** — generated SQL + DataFrame + tables referenced; shows even when 0 rows so the user can debug
  - **Sources** — expandable RAG chunks with similarity scores and metadata
  - **Trace** — intent + confidence + per-stage timings + raw LLM output

---

## Configuration

Every knob lives in `configs/app.yaml` and can be env-overridden using double-underscore notation (`KAFKA__BOOTSTRAP_SERVERS=...`).

Highlights:

```yaml
kafka:
  bootstrap_servers: localhost:9092
  client_id: hcm-analytics
  compression_type: snappy

topics:
  employee_csv: hcm_employee_data

spark:
  master: "local[*]"
  packages:
    - org.apache.spark:spark-sql-kafka-0-10_2.13:4.0.0
    - io.delta:delta-spark_2.13:4.0.0

silver:
  employees:
    dq:
      max_invalid_salary_pct:     0.10
      max_invalid_date_pct:       0.10
      max_unknown_department_pct: 0.05

embeddings:
  model: sentence-transformers/all-MiniLM-L6-v2
  vectors_dir: data/vectors/chroma
  collection_name: hcm_insights
  batch_size: 32

nl2sql:
  ollama:
    base_url: http://localhost:11434
    model: gemma2:2b
    temperature: 0.1
  duckdb:
    gold_root: data/gold
    default_row_limit: 500
    max_result_rows: 10000
  safety:
    allowed_statement_kinds: [Select, With]
    blocked_keywords:
      [ATTACH, COPY, INSTALL, LOAD, PRAGMA, SET, EXPORT, IMPORT,
       READ_TEXT, READ_BLOB]

router:
  conversation:
    history_turns: 6
  classifier:
    enable_rule_tier: true
    enable_llm_tier:  true
    rule_confidence_threshold: 0.75
```

---

## Production-grade design points

| Concern | How it's handled |
|---|---|
| **Config-driven** | All paths, topics, brokers, thresholds in `configs/app.yaml`, env-overridable |
| **Schema as code** | Single `StructType` per stream in `schemas/` — producers and Spark jobs import from one source of truth, no inline redefinitions |
| **Permissive Bronze, strict Silver** | Bronze accepts every row; Silver applies cleaning + DQ gates and can block on critical failures |
| **Idempotent / replayable** | Spark checkpoints, stable upsert keys for RAG chunks, deterministic 0-row paths |
| **Defence-in-depth SQL safety** | LLM output → sql_repair → sql_validator → DuckDB extensions disabled → execution timeout |
| **Cost control on LLM** | Tier-1 rules avoid LLM for ~85% of intent classifications; OFFTOPIC short-circuits before any engine; 0-row analytical short-circuits before synthesis |
| **Graceful degradation** | If Ollama is down → rules + deterministic synth; if RAG empty → SQL-only; if Gold missing → clear status pill with the exact command to fix |
| **Observability** | Structured JSON logs to `logs/hcm.log`; per-message trace tab; status pills; per-stage timings on every `RouterResponse` |
| **Tested** | Pytest fixtures + schema round-trip + transform unit tests (`tests/`) |
| **Reproducible** | Pinned deps, deterministic seeds in producers, containerised Kafka |

---

## Bring your own data

The pipeline assumes 11 columns: `employee_id, name, department, salary, joining_date, performance_rating, manager, attrition, country, skills, experience`.

If your HRIS export has **the same columns** (any spelling/casing variants — Silver canonicalises departments and Gold tolerates messy salaries) — just drop your file at `data/raw/hcm_employees.csv` and run the pipeline.

If your columns are **different**:
1. Update `schemas/hcm_schemas.py` to match your CSV column names.
2. Update the field-name mapping in `producer/csv_to_kafka.py:clean_record()`.
3. Update field-specific logic in `silver/transformations.py` (your salary may not need the `"$50,000"` regex).
4. Existing Gold marts mostly reuse cleanly — only the seven analytical functions in `gold/*.py` reference specific columns.

For a real Kafka cluster (no synthetic CSV), point `kafka.bootstrap_servers` at your broker and `topics.employee_csv` at your topic. Skip the producer entirely; just run Bronze onwards.

---

## Cloud deployment hints

The dashboard has **no JVM dependency** — Spark stays on the pipeline side. To deploy:

| Component | Adjustment |
|---|---|
| Streamlit container | Python 3.11-slim image; copy code + `pip install -r requirements.txt`; `streamlit run` |
| ChromaDB | Bundle `data/vectors/` into the image, or switch to ChromaDB server mode and point `embeddings.vectors_dir` at it |
| Ollama | Sidecar (`ollama/ollama` image) or point `nl2sql.ollama.base_url` at a managed endpoint |
| Gold parquet | DuckDB reads S3/GCS natively — change `lake.gold` in `app.yaml` to `s3://...` |
| Logs | Already structured JSON; pipe `logs/hcm.log` to your aggregator |
| Spark jobs | Run as a separate batch container/cluster (EMR / Dataproc / Databricks) feeding the shared Gold bucket |

Cleanest first cloud target: **Streamlit Community Cloud** for the UI, **AWS Fargate / Cloud Run** for the Ollama sidecar, **AWS Glue / Databricks Jobs** for the Spark pipeline.

---

## Commit log (highlights)

```
fef41a4  Deterministic 0-row response + cache invalidation UI
2ee8ba0  Auto-repair Gemma 2B's bare-table hallucinations
195976b  Few-shot examples in NL→SQL prompt + raw output surfaced
1fa3125  AI Chat page: conversational UI over the hybrid router
e7ef6df  Hybrid router: intent classifier + SQL/RAG dispatch + synth
85874ad  NL→SQL engine: Ollama (Gemma 2B) + DuckDB on Gold parquet
dd17b9b  Embedding pipeline: Gold marts → RAG-ready ChromaDB
af7f1c5  Streamlit dashboard: 5-page Gold-mart BI app
a1efab9  Gold: business analytics marts on Silver dim_employee
59ca6f7  Silver: production-style HCM employee ETL with DQ gating
865ae7c  Bronze: HCM employee Kafka → Parquet (Structured Streaming)
f806350  CSV → Kafka streaming producer (confluent-kafka, config-driven)
b782bd6  Root-level Kafka + Zookeeper docker-compose for local dev
781e87b  Initial commit: HCM analytics big-data pipeline
```

Run `git log --oneline` for the full 24-commit history.

---

## License

MIT (or whatever you choose). This repo is suitable as a portfolio project, a teaching reference for medallion + RAG architectures, or a starting point for a real workforce-analytics product.
