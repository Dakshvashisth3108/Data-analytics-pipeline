"""Performance chunkers."""
from __future__ import annotations

from ..chunk import Chunk, stable_id
from ._helpers import (
    base_metadata, fmt_money, fmt_pct, load_mart, safe_int,
)

DOMAIN = "performance"


def _by_department() -> list[Chunk]:
    df = load_mart(DOMAIN, "by_department")
    if df.empty:
        return []
    snapshot = df["snapshot_date"].iloc[0] if "snapshot_date" in df.columns else None
    chunks: list[Chunk] = []

    for _, row in df.iterrows():
        dept = row["department"]
        text = (
            f"Performance ratings in {dept}: average rating "
            f"{float(row['avg_rating']):.2f}/5 across "
            f"{safe_int(row['rated_employees'])} rated employees. "
            f"High performers (rating >= 4): "
            f"{safe_int(row.get('high_performers'))} "
            f"({fmt_pct(row.get('high_performer_pct'))}). "
            f"Low performers (rating <= 2): "
            f"{safe_int(row.get('low_performers'))} "
            f"({fmt_pct(row.get('low_performer_pct'))})."
        )
        chunks.append(Chunk(
            chunk_id=stable_id(DOMAIN, "by_department", dept=dept),
            text=text,
            metadata=base_metadata(
                DOMAIN, "by_department", snapshot,
                department=dept,
                avg_rating=float(row["avg_rating"]),
                rated_employees=safe_int(row["rated_employees"]),
            ),
        ))

    top = df.sort_values("avg_rating", ascending=False).head(3)
    bottom = df.sort_values("avg_rating", ascending=True).head(3)
    summary = (
        f"Performance leaderboard across {len(df)} departments. "
        f"Top-rated: " + "; ".join(
            f"{r['department']} {float(r['avg_rating']):.2f}"
            for _, r in top.iterrows()
        )
        + ". Lowest-rated: " + "; ".join(
            f"{r['department']} {float(r['avg_rating']):.2f}"
            for _, r in bottom.iterrows()
        ) + "."
    )
    chunks.append(Chunk(
        chunk_id=stable_id(DOMAIN, "by_department", "summary"),
        text=summary,
        metadata=base_metadata(DOMAIN, "by_department", snapshot, kind="summary"),
    ))
    return chunks


def _top_teams() -> list[Chunk]:
    df = load_mart(DOMAIN, "top_teams")
    if df.empty:
        return []
    snapshot = df["snapshot_date"].iloc[0] if "snapshot_date" in df.columns else None
    chunks: list[Chunk] = []

    for _, row in df.iterrows():
        rank = safe_int(row["rank"])
        text = (
            f"Top-performing team #{rank}: {row['department']} with "
            f"average rating {float(row['avg_rating']):.2f}/5 across "
            f"{safe_int(row['rated_employees'])} employees, "
            f"{fmt_pct(row.get('high_performer_pct'))} high-performer share."
        )
        chunks.append(Chunk(
            chunk_id=stable_id(DOMAIN, "top_teams", rank=rank),
            text=text,
            metadata=base_metadata(
                DOMAIN, "top_teams", snapshot,
                rank=rank, department=row["department"],
                avg_rating=float(row["avg_rating"]),
            ),
        ))

    summary = "Top-performing teams: " + " > ".join(
        f"#{safe_int(r['rank'])} {r['department']}" for _, r in df.iterrows()
    ) + "."
    chunks.append(Chunk(
        chunk_id=stable_id(DOMAIN, "top_teams", "summary"),
        text=summary,
        metadata=base_metadata(DOMAIN, "top_teams", snapshot, kind="summary"),
    ))
    return chunks


def _vs_salary() -> list[Chunk]:
    df = load_mart(DOMAIN, "vs_salary")
    if df.empty:
        return []
    snapshot = df["snapshot_date"].iloc[0] if "snapshot_date" in df.columns else None
    chunks: list[Chunk] = []

    for _, row in df.iterrows():
        rating = safe_int(row["performance_rating"])
        text = (
            f"Employees with performance rating {rating}: "
            f"{safe_int(row['employees'])} people, average salary "
            f"{fmt_money(row['avg_salary'])} (median "
            f"{fmt_money(row.get('median_salary'))}, "
            f"min {fmt_money(row.get('min_salary'))}, "
            f"max {fmt_money(row.get('max_salary'))})."
        )
        chunks.append(Chunk(
            chunk_id=stable_id(DOMAIN, "vs_salary", rating=rating),
            text=text,
            metadata=base_metadata(
                DOMAIN, "vs_salary", snapshot,
                performance_rating=rating,
                avg_salary=float(row["avg_salary"]),
            ),
        ))

    if len(df) >= 2:
        df_sorted = df.sort_values("performance_rating")
        low = df_sorted.iloc[0]
        high = df_sorted.iloc[-1]
        gap = float(high["avg_salary"]) - float(low["avg_salary"])
        rel_pct = (gap / float(low["avg_salary"]) * 100) if float(low["avg_salary"]) else 0
        direction = "more" if gap > 0 else "less"
        summary = (
            f"Pay-for-performance signal: rating-{safe_int(high['performance_rating'])} "
            f"employees earn an average of {fmt_money(high['avg_salary'])}, vs "
            f"rating-{safe_int(low['performance_rating'])} at "
            f"{fmt_money(low['avg_salary'])} -- top performers earn "
            f"{fmt_money(abs(gap))} {direction} on average ({rel_pct:+.1f}%)."
        )
        chunks.append(Chunk(
            chunk_id=stable_id(DOMAIN, "vs_salary", "summary"),
            text=summary,
            metadata=base_metadata(DOMAIN, "vs_salary", snapshot, kind="summary"),
        ))
    return chunks


def build() -> list[Chunk]:
    out: list[Chunk] = []
    out += _by_department()
    out += _top_teams()
    out += _vs_salary()
    return out
