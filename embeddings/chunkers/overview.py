"""Cross-domain overview chunks.

These synthesise the most important facts across all four analytic
domains into a handful of high-density chunks. They're what you want a
RAG retriever to surface for broad questions like "give me a company
snapshot" or "what should the CEO know?".
"""
from __future__ import annotations

import pandas as pd

from ..chunk import Chunk, stable_id
from ._helpers import (
    base_metadata, fmt_money, fmt_pct, load_mart, safe_int,
)

DOMAIN = "overview"


def _company_snapshot() -> Chunk | None:
    hc = load_mart("workforce", "by_department")
    sal = load_mart("salary", "distribution")
    perf = load_mart("performance", "by_department")
    if hc.empty:
        return None

    snapshot = hc["snapshot_date"].iloc[0] if "snapshot_date" in hc.columns else None
    total_hc = safe_int(hc["headcount"].sum())
    total_active = safe_int(hc["active"].sum())
    total_attrited = safe_int(hc["attrited"].sum())
    n_depts = hc["department"].nunique()
    overall_attr = total_attrited / total_hc if total_hc else 0

    avg_sal_str = "n/a"
    median_sal_str = "n/a"
    payroll_str = "n/a"
    if not sal.empty:
        s = sal.iloc[0]
        avg_sal_str = fmt_money(s.get("avg_salary"))
        median_sal_str = fmt_money(s.get("median_salary"))
        payroll_str = fmt_money(s.get("total_payroll"))

    perf_str = ""
    if not perf.empty:
        weighted = (
            (perf["avg_rating"] * perf["rated_employees"]).sum()
            / max(perf["rated_employees"].sum(), 1)
        )
        perf_str = (
            f"Average performance rating across all rated employees is "
            f"{weighted:.2f}/5. "
        )

    text = (
        f"Company snapshot: total workforce of {total_hc} employees "
        f"({total_active} active, {total_attrited} attrited) across "
        f"{n_depts} departments. Overall attrition rate is "
        f"{fmt_pct(overall_attr)}. Average salary is {avg_sal_str}, "
        f"median {median_sal_str}, total payroll {payroll_str}. "
        f"{perf_str}"
        f"This snapshot can be used to answer high-level questions about "
        f"size, attrition, compensation, and performance."
    )
    return Chunk(
        chunk_id=stable_id(DOMAIN, "company_snapshot"),
        text=text,
        metadata=base_metadata(
            DOMAIN, "company_snapshot", snapshot,
            kind="summary",
            total_headcount=total_hc,
            attrition_rate=float(overall_attr),
        ),
    )


def _attrition_hotspots() -> Chunk | None:
    df = load_mart("attrition", "by_department")
    if df.empty:
        return None
    snapshot = df["snapshot_date"].iloc[0] if "snapshot_date" in df.columns else None
    top = df.sort_values("attrition_rate", ascending=False).head(3)
    text = (
        "Highest-attrition departments to watch: "
        + "; ".join(
            f"{r['department']} ({fmt_pct(r['attrition_rate'])}, "
            f"{safe_int(r['attrited'])}/{safe_int(r['headcount'])})"
            for _, r in top.iterrows()
        ) + ". These are the priority areas for retention investment."
    )
    return Chunk(
        chunk_id=stable_id(DOMAIN, "attrition_hotspots"),
        text=text,
        metadata=base_metadata(
            DOMAIN, "attrition_hotspots", snapshot, kind="summary",
        ),
    )


def _compensation_leaders() -> Chunk | None:
    df = load_mart("salary", "by_department")
    if df.empty:
        return None
    snapshot = df["snapshot_date"].iloc[0] if "snapshot_date" in df.columns else None
    top = df.sort_values("avg_salary", ascending=False).head(3)
    text = (
        "Highest-paying departments: "
        + "; ".join(
            f"{r['department']} (avg {fmt_money(r['avg_salary'])})"
            for _, r in top.iterrows()
        ) + "."
    )
    return Chunk(
        chunk_id=stable_id(DOMAIN, "compensation_leaders"),
        text=text,
        metadata=base_metadata(
            DOMAIN, "compensation_leaders", snapshot, kind="summary",
        ),
    )


def _talent_density() -> Chunk | None:
    df = load_mart("performance", "by_department")
    if df.empty:
        return None
    snapshot = df["snapshot_date"].iloc[0] if "snapshot_date" in df.columns else None
    top = df.sort_values("high_performer_pct", ascending=False).head(3)
    text = (
        "Highest concentration of high performers (rating >= 4): "
        + "; ".join(
            f"{r['department']} ({fmt_pct(r['high_performer_pct'])} of "
            f"{safe_int(r['rated_employees'])} rated)"
            for _, r in top.iterrows()
        ) + ". These departments have the strongest talent density."
    )
    return Chunk(
        chunk_id=stable_id(DOMAIN, "talent_density"),
        text=text,
        metadata=base_metadata(
            DOMAIN, "talent_density", snapshot, kind="summary",
        ),
    )


def _hiring_pulse() -> Chunk | None:
    df = load_mart("workforce", "hiring_trends")
    if df.empty:
        return None
    snapshot = df["snapshot_date"].iloc[0] if "snapshot_date" in df.columns else None
    yearly = (df.groupby("hire_year")["hires"].sum()
                .reset_index().sort_values("hire_year"))
    if yearly.empty:
        return None
    if len(yearly) >= 2:
        recent = yearly.iloc[-1]
        prior = yearly.iloc[-2]
        text = (
            f"Hiring pulse: {safe_int(recent['hires'])} hires in "
            f"{safe_int(recent['hire_year'])}, "
            f"vs {safe_int(prior['hires'])} in "
            f"{safe_int(prior['hire_year'])}. Total cumulative hires "
            f"recorded: {safe_int(yearly['hires'].sum())}."
        )
    else:
        recent = yearly.iloc[-1]
        text = (
            f"Hiring pulse: {safe_int(recent['hires'])} hires in "
            f"{safe_int(recent['hire_year'])}. Total cumulative hires "
            f"recorded: {safe_int(yearly['hires'].sum())}."
        )
    return Chunk(
        chunk_id=stable_id(DOMAIN, "hiring_pulse"),
        text=text,
        metadata=base_metadata(DOMAIN, "hiring_pulse", snapshot, kind="summary"),
    )


def build() -> list[Chunk]:
    out: list[Chunk] = []
    for fn in (_company_snapshot, _attrition_hotspots, _compensation_leaders,
               _talent_density, _hiring_pulse):
        c = fn()
        if c is not None:
            out.append(c)
    return out
