"""Schema contracts for every HCM event stream.

Each stream is defined once here as a Spark ``StructType``. All producers,
consumers, and Spark jobs MUST import from this module — never redeclare a
schema inline. This is the single source of truth that prevents drift between
the producers and the bronze/silver/gold layers.
"""

from .hcm_schemas import (
    EMPLOYEE_SCHEMA,
    HCM_EMPLOYEE_CSV_SCHEMA,
    ATTENDANCE_SCHEMA,
    PERFORMANCE_SCHEMA,
    RECRUITMENT_SCHEMA,
    SCHEMAS_BY_STREAM,
)

__all__ = [
    "EMPLOYEE_SCHEMA",
    "HCM_EMPLOYEE_CSV_SCHEMA",
    "ATTENDANCE_SCHEMA",
    "PERFORMANCE_SCHEMA",
    "RECRUITMENT_SCHEMA",
    "SCHEMAS_BY_STREAM",
]
