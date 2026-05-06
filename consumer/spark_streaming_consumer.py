"""Convenience alias for the Bronze Structured-Streaming consumer.

The real implementation lives at ``bronze/ingest_employee_stream.py``
(it's the Bronze stage of the Medallion pipeline). This module is a
thin wrapper so either path works:

    python consumer/spark_streaming_consumer.py
    python -m consumer.spark_streaming_consumer
    python -m bronze.ingest_employee_stream            # canonical
"""
from __future__ import annotations

import sys
from pathlib import Path

# sys.path bootstrap so absolute imports resolve when run as a script.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from bronze.ingest_employee_stream import main as _main


if __name__ == "__main__":
    sys.exit(_main())
