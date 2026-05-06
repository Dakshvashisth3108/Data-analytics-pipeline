"""Convenience alias for the Silver ETL job.

The real implementation lives at ``silver/build_silver_employees.py``.
Run either of:

    python silver/silver_etl.py
    python -m silver.silver_etl
    python -m silver.build_silver_employees            # canonical
"""
from __future__ import annotations

import sys
from pathlib import Path

# sys.path bootstrap so absolute imports resolve when run as a script.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from silver.build_silver_employees import main as _main


if __name__ == "__main__":
    sys.exit(_main())
