"""Convenience alias for the Gold analytics ETL.

The real implementation lives at ``gold/build_employee_gold.py``.
Run either of:

    python gold/gold_etl.py
    python -m gold.gold_etl
    python -m gold.build_employee_gold                 # canonical
"""
from __future__ import annotations

import sys
from pathlib import Path

# sys.path bootstrap so absolute imports resolve when run as a script.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from gold.build_employee_gold import main as _main


if __name__ == "__main__":
    sys.exit(_main())
