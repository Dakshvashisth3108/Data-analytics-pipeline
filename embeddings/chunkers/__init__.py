"""Per-domain chunkers — pure pandas DataFrame -> list[Chunk] functions.

Each module owns the natural-language phrasing for its analytics domain.
Adding a new domain = drop a new module here and register it in
``embeddings/build_index.py``.
"""
from .attrition   import build as build_attrition
from .salary      import build as build_salary
from .workforce   import build as build_workforce
from .performance import build as build_performance
from .overview    import build as build_overview

__all__ = [
    "build_attrition",
    "build_salary",
    "build_workforce",
    "build_performance",
    "build_overview",
]
