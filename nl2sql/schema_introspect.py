"""Inspect Gold parquet folders and produce a prompt-friendly schema doc.

Each ``data/gold/<domain>/<metric>/`` becomes one "table" exposed to the
LLM as ``<domain>_<metric>``. We read a single parquet file from each
folder via pyarrow to get the column list + types, without spinning up
DuckDB or Spark just for introspection.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import pyarrow.parquet as pq

from utils import get_logger, gold_path

LOG = get_logger("hcm.nl2sql.schema")


@dataclass
class TableSchema:
    """One DuckDB view = one Gold mart."""
    view_name: str           # e.g. "attrition_by_department"
    domain: str              # e.g. "attrition"
    metric: str              # e.g. "by_department"
    parquet_glob: str        # e.g. ".../data/gold/attrition/by_department/*.parquet"
    columns: list[tuple[str, str]] = field(default_factory=list)  # [(name, dtype), ...]
    row_count_estimate: int | None = None

    def signature(self) -> str:
        cols = ", ".join(f"{n} {t}" for n, t in self.columns)
        return f"{self.view_name}({cols})"


@dataclass
class SchemaCatalog:
    tables: list[TableSchema] = field(default_factory=list)

    def view_names(self) -> list[str]:
        return [t.view_name for t in self.tables]

    def find(self, view: str) -> TableSchema | None:
        for t in self.tables:
            if t.view_name == view:
                return t
        return None

    def to_prompt_doc(self) -> str:
        """Render the catalog as a Markdown-ish block for the LLM."""
        if not self.tables:
            return "(no tables available)"
        lines = [
            "Available DuckDB views (read-only) over Gold parquet:",
            "",
        ]
        # Group by domain for readability
        by_domain: dict[str, list[TableSchema]] = {}
        for t in self.tables:
            by_domain.setdefault(t.domain, []).append(t)
        for domain in sorted(by_domain):
            lines.append(f"### Domain: {domain}")
            for t in sorted(by_domain[domain], key=lambda x: x.metric):
                cols = ", ".join(f"{n} {t}" for n, t in t.columns)
                lines.append(f"- {t.view_name}({cols})")
            lines.append("")
        return "\n".join(lines)


# ── Builder ───────────────────────────────────────────────────────────────
def _scan_metric_folders(root: Path) -> Iterable[tuple[str, str, Path]]:
    """Yield (domain, metric, folder_path) for each Gold mart on disk."""
    if not root.exists():
        return
    for domain_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        for metric_dir in sorted(p for p in domain_dir.iterdir() if p.is_dir()):
            yield (domain_dir.name, metric_dir.name, metric_dir)


def _read_first_parquet_schema(folder: Path) -> list[tuple[str, str]]:
    """Read one parquet file to get its schema. Returns [(name, dtype), ...]."""
    parquet_files = sorted(folder.rglob("*.parquet"))
    if not parquet_files:
        return []
    try:
        schema = pq.read_schema(parquet_files[0])
    except Exception:
        LOG.exception("parquet_schema_read_failed path=%s", parquet_files[0])
        return []
    return [(f.name, str(f.type)) for f in schema]


def build_catalog(gold_root: str | Path | None = None) -> SchemaCatalog:
    """Walk ``data/gold/`` and return a typed catalog of every mart."""
    if gold_root is None:
        gold_root = gold_path("")  # data/gold
    root = Path(gold_root)

    tables: list[TableSchema] = []
    for domain, metric, folder in _scan_metric_folders(root):
        view = f"{domain}_{metric}"
        cols = _read_first_parquet_schema(folder)
        if not cols:
            LOG.warning("skipping empty/invalid mart %s/%s at %s",
                        domain, metric, folder)
            continue
        # DuckDB-friendly POSIX glob
        glob_path = (folder / "*.parquet").as_posix()
        tables.append(TableSchema(
            view_name=view,
            domain=domain,
            metric=metric,
            parquet_glob=glob_path,
            columns=cols,
        ))

    LOG.info("catalog_built tables=%d", len(tables))
    return SchemaCatalog(tables=tables)
