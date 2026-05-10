"""Salary chunkers."""
from __future__ import annotations

from ..chunk import Chunk, stable_id
from ._helpers import (
    base_metadata, fmt_money, load_mart, safe_int,
)

DOMAIN = "salary"


def _by_department() -> list[Chunk]:
    df = load_mart(DOMAIN, "by_department")
    if df.empty:
        return []
    snapshot = df["snapshot_date"].iloc[0] if "snapshot_date" in df.columns else None
    chunks: list[Chunk] = []

    for _, row in df.iterrows():
        dept = row["department"]
        text = (
            f"Salary in the {dept} department: average "
            f"{fmt_money(row['avg_salary'])}, median "
            f"{fmt_money(row['median_salary'])}, "
            f"P25 {fmt_money(row.get('p25_salary'))}, "
            f"P75 {fmt_money(row.get('p75_salary'))}, "
            f"P90 {fmt_money(row.get('p90_salary'))}, "
            f"standard deviation {fmt_money(row.get('stddev_salary'))}. "
            f"Total payroll is {fmt_money(row.get('total_payroll'))} across "
            f"{safe_int(row.get('employees_with_salary'))} employees with "
            f"recorded salaries."
        )
        chunks.append(Chunk(
            chunk_id=stable_id(DOMAIN, "by_department", dept=dept),
            text=text,
            metadata=base_metadata(
                DOMAIN, "by_department", snapshot,
                department=dept,
                avg_salary=float(row["avg_salary"]) if row.get("avg_salary") else None,
                total_payroll=float(row.get("total_payroll", 0)),
            ),
        ))

    top = df.sort_values("avg_salary", ascending=False).head(3)
    bottom = df.sort_values("avg_salary", ascending=True).head(3)
    summary = (
        f"Across {len(df)} departments, top-paying are: "
        + "; ".join(f"{r['department']} {fmt_money(r['avg_salary'])}" for _, r in top.iterrows())
        + ". Lowest-paying are: "
        + "; ".join(f"{r['department']} {fmt_money(r['avg_salary'])}" for _, r in bottom.iterrows())
        + f". Total company payroll across departments: {fmt_money(df['total_payroll'].sum())}."
    )
    chunks.append(Chunk(
        chunk_id=stable_id(DOMAIN, "by_department", "summary"),
        text=summary,
        metadata=base_metadata(DOMAIN, "by_department", snapshot, kind="summary"),
    ))
    return chunks


def _top_paying() -> list[Chunk]:
    df = load_mart(DOMAIN, "top_paying_depts")
    if df.empty:
        return []
    snapshot = df["snapshot_date"].iloc[0] if "snapshot_date" in df.columns else None
    chunks: list[Chunk] = []

    for _, row in df.iterrows():
        rank = safe_int(row["rank"])
        dept = row["department"]
        text = (
            f"Rank #{rank}: {dept} pays an average of "
            f"{fmt_money(row['avg_salary'])} (median "
            f"{fmt_money(row.get('median_salary'))}) across "
            f"{safe_int(row.get('employees_with_salary'))} employees, "
            f"with total payroll of {fmt_money(row.get('total_payroll'))}."
        )
        chunks.append(Chunk(
            chunk_id=stable_id(DOMAIN, "top_paying_depts", rank=rank),
            text=text,
            metadata=base_metadata(
                DOMAIN, "top_paying_depts", snapshot,
                rank=rank, department=dept,
                avg_salary=float(row["avg_salary"]),
            ),
        ))

    summary = (
        "Top-paying departments leaderboard: "
        + " > ".join(f"#{safe_int(r['rank'])} {r['department']}" for _, r in df.iterrows())
        + "."
    )
    chunks.append(Chunk(
        chunk_id=stable_id(DOMAIN, "top_paying_depts", "summary"),
        text=summary,
        metadata=base_metadata(DOMAIN, "top_paying_depts", snapshot, kind="summary"),
    ))
    return chunks


def _distribution() -> list[Chunk]:
    df = load_mart(DOMAIN, "distribution")
    if df.empty:
        return []
    row = df.iloc[0]
    snapshot = row.get("snapshot_date")
    text = (
        f"Company-wide salary distribution: average {fmt_money(row['avg_salary'])}, "
        f"median {fmt_money(row['median_salary'])}, "
        f"P25 {fmt_money(row.get('p25_salary'))}, "
        f"P75 {fmt_money(row.get('p75_salary'))}, "
        f"P90 {fmt_money(row.get('p90_salary'))}, "
        f"P95 {fmt_money(row.get('p95_salary'))}, "
        f"P99 {fmt_money(row.get('p99_salary'))}, "
        f"min {fmt_money(row.get('min_salary'))}, "
        f"max {fmt_money(row.get('max_salary'))}, "
        f"stddev {fmt_money(row.get('stddev_salary'))}. "
        f"Total payroll {fmt_money(row.get('total_payroll'))} across "
        f"{safe_int(row.get('employees_with_salary'))} employees."
    )
    return [Chunk(
        chunk_id=stable_id(DOMAIN, "distribution", "summary"),
        text=text,
        metadata=base_metadata(
            DOMAIN, "distribution", snapshot, kind="summary",
            avg_salary=float(row["avg_salary"]),
        ),
    )]


def build() -> list[Chunk]:
    out: list[Chunk] = []
    out += _by_department()
    out += _top_paying()
    out += _distribution()
    return out
