"""End-to-end orchestrator for local runs.

Sequentially executes the Silver and Gold batch jobs. The Bronze job runs
separately as a long-lived Structured Streaming process.

Usage:
    python run_pipeline.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

JOBS = [
    "silver.build_silver_employees",
    "silver.build_silver_attendance",
    "silver.build_silver_performance",
    "silver.build_silver_recruitment",
    "gold.build_gold_headcount",
    "gold.build_gold_attendance",
    "gold.build_gold_performance",
    "gold.build_gold_recruitment",
]


def run(module: str) -> None:
    print(f"\n=== running {module} ===", flush=True)
    result = subprocess.run([sys.executable, "-m", module], cwd=ROOT)
    if result.returncode != 0:
        raise SystemExit(f"job failed: {module}")


if __name__ == "__main__":
    for m in JOBS:
        run(m)
    print("\n✓ pipeline complete")
