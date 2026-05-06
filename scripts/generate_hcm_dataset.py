"""Synthetic HCM dataset generator with intentional data-quality issues.

Generates 100,000 employee records and writes them as CSV, JSON, and Parquet
under ``data/raw/`` (configurable via ``--out``). Intended as messy upstream
input for the bronze-silver-gold pipeline elsewhere in this repo, or as a
standalone teaching dataset for cleaning and EDA.

Injected issues:
  * NULL values in roughly 5% of cells across nullable columns
  * Duplicate rows (~1%) — same employee_id repeated
  * Malformed salaries: "$50,000", "75k", "N/A", "€42,000.00", etc.
  * Inconsistent department names: "Engineering" / "engineering" / "Engg"
  * Invalid dates: "2025-13-45", "31/02/2024", "not-a-date", ""

Usage:
    python scripts/generate_hcm_dataset.py
    python scripts/generate_hcm_dataset.py --rows 50000 --seed 7 --out ./out
"""
from __future__ import annotations

import argparse
import random
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from faker import Faker

# ── Reference data ─────────────────────────────────────────────────────────
# Each canonical department is paired with the messy variants we will randomly
# emit, so the same logical department appears under several spellings.
DEPARTMENT_VARIANTS: dict[str, list[str]] = {
    "Engineering":     ["Engineering", "engineering", "ENGINEERING", "Engg", "Engg.", "Eng", "Eng."],
    "Sales":           ["Sales", "sales", "SALES", "Sales Dept", "Sales-Team"],
    "Marketing":       ["Marketing", "marketing", "MKTG", "Mktg.", "Marketing Dept"],
    "Finance":         ["Finance", "finance", "FIN", "Fin.", "Finance & Accounts"],
    "Human Resources": ["Human Resources", "HR", "hr", "H.R.", "Human-Resources", "human resources"],
    "Operations":      ["Operations", "Ops", "OPS", "ops", "Op."],
    "Support":         ["Support", "support", "Cust Support", "Customer Support", "CS"],
    "IT":              ["IT", "I.T.", "Information Technology", "Info Tech", "it"],
}

SKILL_POOL = [
    "Python", "SQL", "Java", "Excel", "PowerBI", "Tableau", "AWS", "Azure",
    "GCP", "Spark", "Kafka", "Docker", "Kubernetes", "Leadership",
    "Communication", "Project Management", "Agile", "React", "Node.js",
    "Machine Learning", "Data Analysis", "Salesforce", "SAP", "Negotiation",
    "Recruiting", "Power Automate", "Snowflake", "Databricks", "Airflow",
]

COUNTRIES = [
    "India", "USA", "UK", "Germany", "Singapore", "Australia", "Canada",
    "UAE", "Japan", "Brazil", "Mexico", "France", "Netherlands", "Ireland",
]


# ── Data-quality helpers ───────────────────────────────────────────────────
def _malformed_salary(value: float, rng: random.Random) -> str:
    """Return a string-encoded salary in one of several messy formats."""
    style = rng.choice(["currency", "k_suffix", "comma", "garbage", "euro", "spaces"])
    if style == "currency":
        return f"${value:,.0f}"
    if style == "k_suffix":
        return f"{value / 1000:.0f}k"
    if style == "comma":
        return f"{value:,.2f}"
    if style == "euro":
        return f"€{value:,.0f}"
    if style == "spaces":
        return f"  {value:.2f} INR  "
    return rng.choice(["N/A", "unknown", "TBD", "-", "??", "null"])


def _invalid_date(rng: random.Random) -> str:
    return rng.choice([
        "2025-13-45",
        "31/02/2024",
        "not-a-date",
        "0000-00-00",
        "2099-01-01",
        "32-13-2024",
        "1900-00-15",
        "",
    ])


# ── Generation ─────────────────────────────────────────────────────────────
def generate_clean(n: int, seed: int) -> pd.DataFrame:
    rng = random.Random(seed)
    Faker.seed(seed)
    fake = Faker()

    # A fixed pool of names so managers actually repeat across employees.
    manager_pool = [fake.name() for _ in range(max(50, n // 250))]

    rows: list[dict] = []
    for i in range(1, n + 1):
        canonical = rng.choice(list(DEPARTMENT_VARIANTS.keys()))
        rows.append({
            "employee_id":        f"E{i:06d}",
            "name":               fake.name(),
            "department":         rng.choice(DEPARTMENT_VARIANTS[canonical]),
            "salary":             round(rng.uniform(300_000, 8_000_000), 2),
            "joining_date":       fake.date_between(start_date="-15y", end_date="today").isoformat(),
            "performance_rating": rng.choices([1, 2, 3, 4, 5], weights=[0.05, 0.10, 0.55, 0.22, 0.08])[0],
            "manager":            rng.choice(manager_pool),
            "attrition":          rng.choices(["Yes", "No"], weights=[0.15, 0.85])[0],
            "country":            rng.choice(COUNTRIES),
            "skills":             rng.sample(SKILL_POOL, k=rng.randint(2, 7)),
            "experience":         rng.randint(0, 35),
        })
    return pd.DataFrame(rows)


def inject_quality_issues(df: pd.DataFrame, seed: int) -> pd.DataFrame:
    rng = random.Random(seed + 1)
    n = len(df)

    # Switch dtypes to object so we can write strings/None freely.
    df["salary"] = df["salary"].astype(object)
    df["joining_date"] = df["joining_date"].astype(object)

    # 1. Malformed salaries (~3%)
    for i in rng.sample(range(n), k=int(n * 0.03)):
        df.at[i, "salary"] = _malformed_salary(float(df.at[i, "salary"]), rng)

    # 2. Invalid dates (~2%)
    for i in rng.sample(range(n), k=int(n * 0.02)):
        df.at[i, "joining_date"] = _invalid_date(rng)

    # 3. NULL injection — ~5% of values per nullable column, independent samples
    nullable_cols = [
        "name", "department", "salary", "joining_date", "performance_rating",
        "manager", "country", "skills", "experience",
    ]
    for col in nullable_cols:
        idx = rng.sample(range(n), k=int(n * 0.05))
        df.loc[idx, col] = None

    # 4. Duplicate rows (~1%) — append exact copies, then shuffle
    dup_idx = rng.sample(range(n), k=int(n * 0.01))
    df = pd.concat([df, df.iloc[dup_idx]], ignore_index=True)
    df = df.sample(frac=1, random_state=seed).reset_index(drop=True)
    return df


# ── Output ─────────────────────────────────────────────────────────────────
def save_outputs(df: pd.DataFrame, out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}

    # CSV — flatten skills list to pipe-delimited string for round-trip safety
    csv_df = df.copy()
    csv_df["skills"] = csv_df["skills"].apply(
        lambda v: "|".join(v) if isinstance(v, list) else v
    )
    paths["csv"] = out_dir / "hcm_employees.csv"
    csv_df.to_csv(paths["csv"], index=False)

    # JSON — keeps skills as native list[str]
    paths["json"] = out_dir / "hcm_employees.json"
    df.to_json(paths["json"], orient="records",
               date_format="iso", force_ascii=False, indent=2)

    # Parquet — cast dirty columns to string so PyArrow doesn't reject the
    # mixed-type cells. skills stays as list<string>.
    pq_df = df.copy()
    pq_df["salary"] = pq_df["salary"].astype("string")
    pq_df["joining_date"] = pq_df["joining_date"].astype("string")
    pq_df["performance_rating"] = pq_df["performance_rating"].astype("Int8")
    pq_df["experience"] = pq_df["experience"].astype("Int8")
    paths["parquet"] = out_dir / "hcm_employees.parquet"
    table = pa.Table.from_pandas(pq_df, preserve_index=False)
    pq.write_table(table, paths["parquet"], compression="snappy")

    return paths


def summarise(df: pd.DataFrame) -> None:
    bar = "-" * 56
    print("\n" + bar)
    print("Summary")
    print(bar)
    print(f"rows total          : {len(df):,}")
    print(f"unique employee_id  : {df['employee_id'].nunique():,}")
    print(f"duplicate rows      : {df['employee_id'].duplicated().sum():,}")
    print(f"distinct dept names : {df['department'].dropna().nunique()} "
          f"(canonical = {len(DEPARTMENT_VARIANTS)})")
    nulls = df.isna().sum()
    print("null counts:")
    for col, n in nulls.items():
        if n:
            print(f"  {col:<20} {n:>7,}  ({n/len(df):.1%})")
    print(bar + "\n")


# ── Entrypoint ─────────────────────────────────────────────────────────────
def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Synthetic HCM dataset generator")
    p.add_argument("--rows", type=int, default=100_000, help="Records to generate before duplicates")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--out",  type=Path,
                   default=Path(__file__).resolve().parents[1] / "data" / "raw")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    print(f"generating  rows={args.rows:,}  seed={args.seed}")
    df = generate_clean(args.rows, args.seed)
    print("injecting data-quality issues ...")
    df = inject_quality_issues(df, args.seed)
    summarise(df)
    print(f"writing outputs to {args.out} ...")
    paths = save_outputs(df, args.out)
    for fmt, p in paths.items():
        size_mb = p.stat().st_size / 1024 / 1024
        print(f"  {fmt:<7} {p}  ({size_mb:.1f} MB)")
    print("done.")


if __name__ == "__main__":
    main()
