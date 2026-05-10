"""CLI: ask the NL->SQL engine a question.

Usage::

    python -m nl2sql.ask "Which department has the highest attrition rate?"
    python -m nl2sql.ask "Top 3 paying departments?" --json
    python -m nl2sql.ask --schema-only          # print the schema doc and exit
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# sys.path bootstrap so direct invocation works.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from utils import get_logger

from nl2sql.engine import NL2SQLEngine

LOG = get_logger("hcm.nl2sql.ask")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Natural-language SQL over the HCM Gold layer.",
    )
    p.add_argument("question", nargs="?", default=None,
                   help="The natural-language question.")
    p.add_argument("--json", action="store_true",
                   help="Emit the structured AnswerResult as JSON.")
    p.add_argument("--schema-only", action="store_true",
                   help="Print the auto-generated schema doc and exit.")
    p.add_argument("--max-rows-shown", type=int, default=20,
                   help="Pretty-print at most this many rows (default 20).")
    return p.parse_args()


def _print_table(columns: list[str], rows: list[dict], limit: int) -> None:
    if not columns or not rows:
        print("(no rows)")
        return
    rows = rows[:limit]
    widths = {c: max(len(str(c)), max(len(str(r.get(c, ""))) for r in rows))
              for c in columns}
    sep = "  ".join("-" * widths[c] for c in columns)
    header = "  ".join(f"{c:<{widths[c]}}" for c in columns)
    print(header)
    print(sep)
    for r in rows:
        print("  ".join(f"{str(r.get(c, '')):<{widths[c]}}" for c in columns))


def main() -> int:
    args = parse_args()

    if args.schema_only:
        engine = NL2SQLEngine()
        print(engine.catalog.to_prompt_doc())
        return 0

    if not args.question:
        print("Error: question is required (or pass --schema-only).",
              file=sys.stderr)
        return 2

    engine = NL2SQLEngine()
    result = engine.ask(args.question)

    if args.json:
        print(json.dumps(result.to_dict(), default=str, indent=2))
        return 0 if not result.error and not result.cannot_answer else 1

    print(f"\nQ: {result.question}")
    if result.error:
        print(f"\nERROR: {result.error}")
        if result.sql:
            print(f"\nGenerated SQL (rejected/failed):\n{result.sql}")
        return 1
    if result.cannot_answer:
        print(f"\nThe model declined to answer:\n{result.sql}")
        return 1

    print(f"\nSQL:\n{result.sql}")
    print(f"\nReferenced tables: {', '.join(result.referenced_tables) or '-'}")
    print(f"LLM: {result.elapsed_ms_llm} ms | DuckDB: {result.elapsed_ms_sql} ms")
    print(f"Rows: {result.row_count}\n")
    _print_table(result.columns, result.rows, args.max_rows_shown)
    if result.row_count > args.max_rows_shown:
        print(f"\n(... {result.row_count - args.max_rows_shown} more rows truncated)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
