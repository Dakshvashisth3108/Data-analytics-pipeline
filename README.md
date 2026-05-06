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

## Prerequisites

| Tool | Version | Notes |
|------|---------|-------|
| **Java** | **26.0.1** (JDK) | Spark 4.0 + Hadoop 3.4 supports Java 17 / 21 / 25 / 26+. The project's `utils/spark.py` injects the required `--add-opens` flags for strong-encapsulation JDKs (Java 17+). |
| **Python** | 3.10+ | Tested with 3.13 on Windows. |
| **PySpark** | 4.0.0 | Pinned in `requirements.txt`. Spark 4 dropped Scala 2.12 — Kafka connector is `_2.13`. |
| **Docker Desktop** | latest | For the Kafka + Zookeeper stack. |
| **Hadoop winutils** | 3.4 | Windows only. Set `HADOOP_HOME` to a folder containing `bin\winutils.exe`. |

```powershell
# Verify Java 26 is the active JDK
java -version            # -> openjdk version "26.0.1"
echo $env:JAVA_HOME      # should point to your Java 26 install
```

If you have multiple JDKs installed, pin Java 26 for this session:
```powershell
$env:JAVA_HOME = "C:\Program Files\Eclipse Adoptium\jdk-26.0.1+something"
$env:Path = "$env:JAVA_HOME\bin;$env:Path"
```

## Quickstart

```powershell
# 1. Start Kafka + Zookeeper
docker compose up -d

# 2. Create + activate a venv, then install Python deps
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 3. Generate the synthetic 10k-row HCM dataset (one-time)
python scripts/generate_hcm_dataset.py --rows 10000

# 4. Stream the CSV into Kafka (continuous)
python -m producer.csv_to_kafka --max-records 5000 --no-loop --delay 0

# 5. Bronze: Kafka -> raw parquet (Structured Streaming)
python -m bronze.ingest_employee_stream --once

# 6. Silver: clean + standardise -> dim_employee
python -m silver.build_silver_employees

# 7. Gold: business-ready marts
python -m gold.build_employee_gold

# 8. Launch the dashboard
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
