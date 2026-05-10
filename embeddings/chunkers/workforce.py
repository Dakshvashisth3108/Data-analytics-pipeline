"""Workforce chunkers."""
from __future__ import annotations

from ..chunk import Chunk, stable_id
from ._helpers import (
    base_metadata, fmt_pct, load_mart, safe_int,
)

DOMAIN = "workforce"


def _by_country() -> list[Chunk]:
    df = load_mart(DOMAIN, "by_country")
    if df.empty:
        return []
    snapshot = df["snapshot_date"].iloc[0] if "snapshot_date" in df.columns else None
    chunks: list[Chunk] = []

    for _, row in df.iterrows():
        country = row["country"]
        text = (
            f"Workforce in {country}: total {safe_int(row['headcount'])} "
            f"({safe_int(row['active'])} active, "
            f"{safe_int(row['attrited'])} attrited; "
            f"{fmt_pct(row.get('active_pct'))} active)."
        )
        chunks.append(Chunk(
            chunk_id=stable_id(DOMAIN, "by_country", country=country),
            text=text,
            metadata=base_metadata(
                DOMAIN, "by_country", snapshot,
                country=country,
                headcount=safe_int(row["headcount"]),
            ),
        ))

    top = df.sort_values("headcount", ascending=False).head(3)
    summary = (
        f"Workforce spans {len(df)} countries with total headcount of "
        f"{safe_int(df['headcount'].sum())}. Largest geographies: "
        + "; ".join(
            f"{r['country']} ({safe_int(r['headcount'])})"
            for _, r in top.iterrows()
        ) + "."
    )
    chunks.append(Chunk(
        chunk_id=stable_id(DOMAIN, "by_country", "summary"),
        text=summary,
        metadata=base_metadata(DOMAIN, "by_country", snapshot, kind="summary"),
    ))
    return chunks


def _by_department() -> list[Chunk]:
    df = load_mart(DOMAIN, "by_department")
    if df.empty:
        return []
    snapshot = df["snapshot_date"].iloc[0] if "snapshot_date" in df.columns else None
    chunks: list[Chunk] = []

    for _, row in df.iterrows():
        dept = row["department"]
        text = (
            f"The {dept} department has {safe_int(row['headcount'])} "
            f"employees: {safe_int(row['active'])} active and "
            f"{safe_int(row['attrited'])} attrited "
            f"({fmt_pct(row.get('active_pct'))} active rate)."
        )
        chunks.append(Chunk(
            chunk_id=stable_id(DOMAIN, "by_department", dept=dept),
            text=text,
            metadata=base_metadata(
                DOMAIN, "by_department", snapshot,
                department=dept,
                headcount=safe_int(row["headcount"]),
            ),
        ))

    top = df.sort_values("headcount", ascending=False).head(3)
    summary = (
        f"Departments by headcount across {len(df)} departments. "
        f"Largest: " + "; ".join(
            f"{r['department']} ({safe_int(r['headcount'])})"
            for _, r in top.iterrows()
        )
        + f". Total active workforce: {safe_int(df['active'].sum())}."
    )
    chunks.append(Chunk(
        chunk_id=stable_id(DOMAIN, "by_department", "summary"),
        text=summary,
        metadata=base_metadata(DOMAIN, "by_department", snapshot, kind="summary"),
    ))
    return chunks


def _experience() -> list[Chunk]:
    df = load_mart(DOMAIN, "experience_distribution")
    if df.empty:
        return []
    snapshot = df["snapshot_date"].iloc[0] if "snapshot_date" in df.columns else None
    chunks: list[Chunk] = []

    for _, row in df.iterrows():
        bucket = row["experience_bucket"]
        text = (
            f"In the {bucket} experience band, headcount is "
            f"{safe_int(row['headcount'])}, representing "
            f"{fmt_pct(row.get('share_pct'))} of the workforce."
        )
        chunks.append(Chunk(
            chunk_id=stable_id(DOMAIN, "experience_distribution", bucket=bucket),
            text=text,
            metadata=base_metadata(
                DOMAIN, "experience_distribution", snapshot,
                experience_bucket=bucket,
                headcount=safe_int(row["headcount"]),
            ),
        ))

    summary = (
        "Seniority pyramid: "
        + " | ".join(
            f"{r['experience_bucket']} {safe_int(r['headcount'])} "
            f"({fmt_pct(r.get('share_pct'))})"
            for _, r in df.iterrows()
        )
    )
    chunks.append(Chunk(
        chunk_id=stable_id(DOMAIN, "experience_distribution", "summary"),
        text=summary,
        metadata=base_metadata(DOMAIN, "experience_distribution", snapshot, kind="summary"),
    ))
    return chunks


def _hiring_trends() -> list[Chunk]:
    df = load_mart(DOMAIN, "hiring_trends")
    if df.empty:
        return []
    snapshot = df["snapshot_date"].iloc[0] if "snapshot_date" in df.columns else None
    chunks: list[Chunk] = []

    # Year-level rollup is more useful than monthly for RAG narrative.
    yearly = (df.groupby("hire_year")["hires"].sum()
                .reset_index().sort_values("hire_year"))
    for _, row in yearly.iterrows():
        year = safe_int(row["hire_year"])
        text = f"In {year}, the company made {safe_int(row['hires'])} hires."
        chunks.append(Chunk(
            chunk_id=stable_id(DOMAIN, "hiring_trends", year=year),
            text=text,
            metadata=base_metadata(
                DOMAIN, "hiring_trends", snapshot,
                hire_year=year, hires=safe_int(row["hires"]),
            ),
        ))

    if len(yearly) >= 2:
        peak = yearly.loc[yearly["hires"].idxmax()]
        recent = yearly.iloc[-1]
        prior = yearly.iloc[-2]
        delta = recent["hires"] - prior["hires"]
        direction = "up" if delta > 0 else ("flat" if delta == 0 else "down")
        summary = (
            f"Hiring trend across {len(yearly)} years. Peak year: "
            f"{safe_int(peak['hire_year'])} with {safe_int(peak['hires'])} "
            f"hires. Latest year ({safe_int(recent['hire_year'])}): "
            f"{safe_int(recent['hires'])} hires, {direction} from "
            f"{safe_int(prior['hires'])} the year before."
        )
        chunks.append(Chunk(
            chunk_id=stable_id(DOMAIN, "hiring_trends", "summary"),
            text=summary,
            metadata=base_metadata(DOMAIN, "hiring_trends", snapshot, kind="summary"),
        ))
    return chunks


def build() -> list[Chunk]:
    out: list[Chunk] = []
    out += _by_country()
    out += _by_department()
    out += _experience()
    out += _hiring_trends()
    return out
