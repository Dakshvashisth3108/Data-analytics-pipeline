"""Attrition chunkers — turn 4 attrition marts into narrative chunks."""
from __future__ import annotations

import pandas as pd

from ..chunk import Chunk, stable_id
from ._helpers import (
    base_metadata, fmt_pct, load_mart, safe_int,
)

DOMAIN = "attrition"


def _by_department() -> list[Chunk]:
    df = load_mart(DOMAIN, "by_department")
    if df.empty:
        return []
    snapshot = df["snapshot_date"].iloc[0] if "snapshot_date" in df.columns else None
    chunks: list[Chunk] = []

    for _, row in df.iterrows():
        dept = row["department"]
        text = (
            f"In the {dept} department, total headcount is "
            f"{safe_int(row['headcount'])} employees, with "
            f"{safe_int(row['attrited'])} who have left and "
            f"{safe_int(row['active'])} still active. The attrition rate "
            f"is {fmt_pct(row['attrition_rate'])}."
        )
        chunks.append(Chunk(
            chunk_id=stable_id(DOMAIN, "by_department", dept=dept),
            text=text,
            metadata=base_metadata(
                DOMAIN, "by_department", snapshot,
                department=dept,
                attrition_rate=float(row["attrition_rate"]),
                headcount=safe_int(row["headcount"]),
            ),
        ))

    # Summary chunk — top + bottom
    sorted_df = df.sort_values("attrition_rate", ascending=False)
    top3 = ", ".join(
        f"{r['department']} ({fmt_pct(r['attrition_rate'])})"
        for _, r in sorted_df.head(3).iterrows()
    )
    bottom3 = ", ".join(
        f"{r['department']} ({fmt_pct(r['attrition_rate'])})"
        for _, r in sorted_df.tail(3).iterrows()
    )
    total_hc = safe_int(df["headcount"].sum())
    total_at = safe_int(df["attrited"].sum())
    overall_rate = total_at / total_hc if total_hc else 0
    summary = (
        f"Across {len(df)} departments, the overall attrition rate is "
        f"{fmt_pct(overall_rate)} ({total_at:,} employees left out of "
        f"{total_hc:,}). The departments with the highest attrition are "
        f"{top3}. The departments with the lowest attrition are {bottom3}."
    )
    chunks.append(Chunk(
        chunk_id=stable_id(DOMAIN, "by_department", "summary"),
        text=summary,
        metadata=base_metadata(DOMAIN, "by_department", snapshot, kind="summary"),
    ))
    return chunks


def _by_country() -> list[Chunk]:
    df = load_mart(DOMAIN, "by_country")
    if df.empty:
        return []
    snapshot = df["snapshot_date"].iloc[0] if "snapshot_date" in df.columns else None
    chunks: list[Chunk] = []

    for _, row in df.iterrows():
        country = row["country"]
        text = (
            f"In {country}, headcount is {safe_int(row['headcount'])} "
            f"with {safe_int(row['attrited'])} attritions, giving an "
            f"attrition rate of {fmt_pct(row['attrition_rate'])}."
        )
        chunks.append(Chunk(
            chunk_id=stable_id(DOMAIN, "by_country", country=country),
            text=text,
            metadata=base_metadata(
                DOMAIN, "by_country", snapshot,
                country=country,
                attrition_rate=float(row["attrition_rate"]),
                headcount=safe_int(row["headcount"]),
            ),
        ))

    top = df.sort_values("attrition_rate", ascending=False).head(3)
    summary = "Geographic attrition concentration: " + "; ".join(
        f"{r['country']} {fmt_pct(r['attrition_rate'])}"
        for _, r in top.iterrows()
    ) + f". Workforce spans {len(df)} countries."
    chunks.append(Chunk(
        chunk_id=stable_id(DOMAIN, "by_country", "summary"),
        text=summary,
        metadata=base_metadata(DOMAIN, "by_country", snapshot, kind="summary"),
    ))
    return chunks


def _trend_by_cohort() -> list[Chunk]:
    df = load_mart(DOMAIN, "trend_by_cohort")
    if df.empty:
        return []
    snapshot = df["snapshot_date"].iloc[0] if "snapshot_date" in df.columns else None
    chunks: list[Chunk] = []

    df = df.sort_values("hire_year")
    for _, row in df.iterrows():
        year = safe_int(row["hire_year"])
        text = (
            f"Employees who joined in {year}: {safe_int(row['headcount'])} "
            f"hired, {safe_int(row['attrited'])} have since left "
            f"(attrition rate {fmt_pct(row['attrition_rate'])})."
        )
        chunks.append(Chunk(
            chunk_id=stable_id(DOMAIN, "trend_by_cohort", year=year),
            text=text,
            metadata=base_metadata(
                DOMAIN, "trend_by_cohort", snapshot,
                hire_year=year,
                attrition_rate=float(row["attrition_rate"]),
            ),
        ))

    worst = df.sort_values("attrition_rate", ascending=False).head(2)
    summary = (
        "Hire-cohort attrition trend: the cohorts with the highest churn are "
        + ", ".join(
            f"{safe_int(r['hire_year'])} ({fmt_pct(r['attrition_rate'])})"
            for _, r in worst.iterrows()
        )
        + f". Coverage spans {df['hire_year'].min()}-{df['hire_year'].max()}."
    )
    chunks.append(Chunk(
        chunk_id=stable_id(DOMAIN, "trend_by_cohort", "summary"),
        text=summary,
        metadata=base_metadata(DOMAIN, "trend_by_cohort", snapshot, kind="summary"),
    ))
    return chunks


def _by_tenure_bucket() -> list[Chunk]:
    df = load_mart(DOMAIN, "by_tenure_bucket")
    if df.empty:
        return []
    snapshot = df["snapshot_date"].iloc[0] if "snapshot_date" in df.columns else None
    chunks: list[Chunk] = []

    for _, row in df.iterrows():
        bucket = row["tenure_bucket"]
        text = (
            f"For employees with {bucket} of tenure, headcount is "
            f"{safe_int(row['headcount'])} and attrition rate is "
            f"{fmt_pct(row['attrition_rate'])}."
        )
        chunks.append(Chunk(
            chunk_id=stable_id(DOMAIN, "by_tenure_bucket", bucket=bucket),
            text=text,
            metadata=base_metadata(
                DOMAIN, "by_tenure_bucket", snapshot,
                tenure_bucket=bucket,
                attrition_rate=float(row["attrition_rate"]),
            ),
        ))

    worst = df.sort_values("attrition_rate", ascending=False).head(1).iloc[0]
    summary = (
        f"Attrition by tenure: the highest-churn tenure bucket is "
        f"{worst['tenure_bucket']} ({fmt_pct(worst['attrition_rate'])}). "
        f"Tenure analysis can guide retention investments at specific "
        f"career stages."
    )
    chunks.append(Chunk(
        chunk_id=stable_id(DOMAIN, "by_tenure_bucket", "summary"),
        text=summary,
        metadata=base_metadata(DOMAIN, "by_tenure_bucket", snapshot, kind="summary"),
    ))
    return chunks


def build() -> list[Chunk]:
    """Produce all attrition chunks."""
    out: list[Chunk] = []
    out += _by_department()
    out += _by_country()
    out += _trend_by_cohort()
    out += _by_tenure_bucket()
    return out
