# HCM Analytics — Big Data Pipeline

Production-grade Human Capital Management (HCM) analytics platform built on Kafka, PySpark, and the Medallion (Bronze/Silver/Gold) architecture, with a Streamlit dashboard on top.

## Architecture

```
 ┌───────────┐    ┌────────┐    ┌──────────────┐    ┌──────────┐    ┌──────────┐
 │ Producers │ -> │ Kafka  │ -> │ Spark Bronze │ -> │  Silver  │ -> │   Gold   │
 │ (HRIS,    │    │ topics │    │ (raw parquet)│    │ (cleaned)│    │ (KPIs)   │
 │  ATS,...) │    └────────┘    └──────────────┘    └──────────┘    └──────────┘
 └───────────┘                                                            │
                                                                          v
                                                                 ┌────────────────┐
                                                                 │ Streamlit dash │
                                                                 └────────────────┘
```

### Domain — HCM
The pipeline ingests four core HCM event streams:

| Stream            | Topic                | Description                                    |
|-------------------|----------------------|------------------------------------------------|
| `employees`       | `hcm.employees`      | Master employee records (SCD-2 in Silver)      |
| `attendance`      | `hcm.attendance`     | Daily punch-in/out & leave events              |
| `performance`     | `hcm.performance`    | Performance review cycles & ratings            |
| `recruitment`     | `hcm.recruitment`    | Applicant funnel events                        |

### Medallion layers
- **Bronze** — Raw immutable Parquet, partitioned by ingestion date. Schema-on-read, append-only.
- **Silver** — Cleansed, deduplicated, type-cast, conformed. SCD-2 for slowly-changing dimensions.
- **Gold** — Business-ready aggregates: headcount KPIs, attrition, attendance compliance, performance distributions, hiring funnel.

## Quickstart

```bash
# 1. Start the stack (Kafka, Zookeeper, Spark, Schema Registry)
cd docker && docker compose up -d

# 2. Install Python deps
pip install -r requirements.txt

# 3. Produce sample HCM events
python -m producer.run --stream employees --rate 50

# 4. Run the bronze ingest job (Structured Streaming)
spark-submit bronze/ingest_bronze.py --topic hcm.employees

# 5. Run silver/gold batch jobs
spark-submit silver/build_silver_employees.py
spark-submit gold/build_gold_headcount.py

# 6. Launch the dashboard
streamlit run streamlit_dashboard/app.py
```

## Layout

```
hcm-analytics/
├── producer/              # Kafka producers (sim + real connectors)
├── consumer/              # Standalone Kafka consumers (audit/replay)
├── bronze/                # Spark jobs: Kafka → Bronze parquet
├── silver/                # Spark jobs: Bronze → Silver
├── gold/                  # Spark jobs: Silver → Gold (KPIs)
├── schemas/               # Avro/JSON schemas + Spark StructType defs
├── configs/               # YAML configs (env-overridable)
├── utils/                 # Shared helpers (spark, logging, io)
├── docker/                # docker-compose + Dockerfiles
├── notebooks/             # Exploratory notebooks
├── streamlit_dashboard/   # Streamlit BI app
├── tests/                 # Unit + integration tests
├── logs/                  # Runtime logs (gitignored)
└── data/                  # Local lakehouse root (gitignored)
    ├── bronze/  silver/  gold/  checkpoints/
```

## Best practices applied
- **Config-driven**: all paths, topics, brokers via `configs/*.yaml` + env overrides.
- **Idempotent writes**: Spark checkpointing + merge keys for Silver/Gold.
- **Schema enforcement**: explicit `StructType` for every stream — no schema drift.
- **Separation of concerns**: ingest (bronze), conform (silver), serve (gold).
- **Observability**: structured JSON logs, Spark UI, metrics-ready.
- **Reproducibility**: containerised stack, pinned deps, deterministic seeds in producers.
- **Tested**: pytest suite for transformations and schema contracts.
