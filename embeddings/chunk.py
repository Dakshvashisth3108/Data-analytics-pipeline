"""Chunk = one self-contained business-insight text unit ready for embedding.

A chunk is what gets stored in the vector DB. Each one needs:
    * a STABLE id (so re-running the pipeline upserts in place)
    * the natural-language text
    * structured metadata (domain, metric, dimension, snapshot_date, ...)
      so retrievals can filter ("show me only attrition insights from
      this week's snapshot, only for Engineering").
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # ChromaDB requires metadata values to be primitive types
        # (str/int/float/bool/None). Coerce defensively.
        cleaned: dict[str, Any] = {}
        for k, v in self.metadata.items():
            if v is None or isinstance(v, (str, int, float, bool)):
                cleaned[k] = v
            else:
                cleaned[k] = str(v)
        # frozen dataclass doesn't allow normal assignment
        object.__setattr__(self, "metadata", cleaned)


def stable_id(*parts: Any, **kw: Any) -> str:
    """Build a deterministic, human-readable chunk id.

    Positional args become flat segments; keyword args become
    ``key=value`` segments (sorted for stability). Mixed usage is
    supported.

    Examples::

        stable_id("attrition", "by_department", dept="Engineering")
        # -> "attrition.by_department.dept=Engineering"

        stable_id("salary", "top_paying_depts", rank=1)
        # -> "salary.top_paying_depts.rank=1"
    """
    out: list[str] = []
    for p in parts:
        if isinstance(p, dict):
            for k, v in sorted(p.items()):
                out.append(f"{k}={v}")
        else:
            out.append(str(p))
    for k, v in sorted(kw.items()):
        out.append(f"{k}={v}")
    # ChromaDB ids must be strings; spaces are fine but we replace them
    # for readability and trim the length cap.
    return ".".join(out).replace(" ", "_")[:512]
