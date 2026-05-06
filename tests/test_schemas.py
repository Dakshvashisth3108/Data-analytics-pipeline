"""Schema contract tests — generators must emit dicts that parse cleanly."""
from __future__ import annotations

import json

from pyspark.sql import functions as F

from producer.generators import HcmGenerator
from schemas import SCHEMAS_BY_STREAM


def _take(gen, n):
    out = []
    for _ in range(n):
        out.append(next(gen))
    return out


def test_employee_schema_round_trip(spark):
    g = HcmGenerator(seed=1, roster_size=10)
    rows = _take(g.stream("employees"), 20)
    df = spark.createDataFrame([{"_raw": json.dumps(r, default=str)} for r in rows])
    parsed = df.select(F.from_json("_raw", SCHEMAS_BY_STREAM["employees"]).alias("p")).select("p.*")
    assert parsed.filter(F.col("employee_id").isNull()).count() == 0
    assert parsed.count() == 20


def test_attendance_schema_round_trip(spark):
    g = HcmGenerator(seed=2, roster_size=5)
    rows = _take(g.stream("attendance"), 10)
    df = spark.createDataFrame([{"_raw": json.dumps(r, default=str)} for r in rows])
    parsed = df.select(F.from_json("_raw", SCHEMAS_BY_STREAM["attendance"]).alias("p")).select("p.*")
    assert parsed.count() == 10
    assert parsed.filter(F.col("attendance_id").isNull()).count() == 0
