"""sys.path bootstrap for the dashboard.

Streamlit's runner sets sys.path[0] to the entry script's directory
(i.e. ``streamlit_dashboard/``), but we want ``utils`` and the project
config to be importable too. Importing ``components`` runs this module
as a side effect and inserts the project root.
"""
from __future__ import annotations

import sys
from pathlib import Path

_DASHBOARD = Path(__file__).resolve().parents[1]   # streamlit_dashboard/
_PROJECT   = _DASHBOARD.parent                      # hcm-analytics/

for _p in (_PROJECT, _DASHBOARD):
    _s = str(_p)
    if _s not in sys.path:
        sys.path.insert(0, _s)
