"""Spark schemas for the four HCM event streams."""
from __future__ import annotations

from pyspark.sql.types import (
    StructType,
    StructField,
    StringType,
    IntegerType,
    DoubleType,
    TimestampType,
    DateType,
    BooleanType,
)

EMPLOYEE_SCHEMA = StructType([
    StructField("employee_id",     StringType(),    False),
    StructField("first_name",      StringType(),    True),
    StructField("last_name",       StringType(),    True),
    StructField("email",           StringType(),    True),
    StructField("gender",          StringType(),    True),
    StructField("date_of_birth",   DateType(),      True),
    StructField("hire_date",       DateType(),      True),
    StructField("termination_date",DateType(),      True),
    StructField("department",      StringType(),    True),
    StructField("job_title",       StringType(),    True),
    StructField("grade",           StringType(),    True),
    StructField("manager_id",      StringType(),    True),
    StructField("location",        StringType(),    True),
    StructField("country",         StringType(),    True),
    StructField("employment_type", StringType(),    True),  # FT/PT/Contract
    StructField("base_salary",     DoubleType(),    True),
    StructField("currency",        StringType(),    True),
    StructField("is_active",       BooleanType(),   True),
    StructField("event_ts",        TimestampType(), False),
])

ATTENDANCE_SCHEMA = StructType([
    StructField("attendance_id",   StringType(),    False),
    StructField("employee_id",     StringType(),    False),
    StructField("work_date",       DateType(),      False),
    StructField("punch_in",        TimestampType(), True),
    StructField("punch_out",       TimestampType(), True),
    StructField("hours_worked",    DoubleType(),    True),
    StructField("status",          StringType(),    True),  # present/absent/leave/wfh
    StructField("leave_type",      StringType(),    True),  # casual/sick/earned/none
    StructField("is_late",         BooleanType(),   True),
    StructField("event_ts",        TimestampType(), False),
])

PERFORMANCE_SCHEMA = StructType([
    StructField("review_id",       StringType(),    False),
    StructField("employee_id",     StringType(),    False),
    StructField("cycle",           StringType(),    False),  # e.g. 2026-H1
    StructField("rating",          IntegerType(),   True),   # 1..5
    StructField("rating_label",    StringType(),    True),
    StructField("goals_met_pct",   DoubleType(),    True),
    StructField("reviewer_id",     StringType(),    True),
    StructField("comments",        StringType(),    True),
    StructField("promotion_flag",  BooleanType(),   True),
    StructField("bonus_amount",    DoubleType(),    True),
    StructField("event_ts",        TimestampType(), False),
])

RECRUITMENT_SCHEMA = StructType([
    StructField("application_id",  StringType(),    False),
    StructField("requisition_id",  StringType(),    False),
    StructField("candidate_id",    StringType(),    False),
    StructField("source",          StringType(),    True),   # referral/linkedin/etc
    StructField("stage",           StringType(),    True),   # applied/screen/interview/offer/hired/rejected
    StructField("department",      StringType(),    True),
    StructField("job_title",       StringType(),    True),
    StructField("location",        StringType(),    True),
    StructField("recruiter_id",    StringType(),    True),
    StructField("offer_amount",    DoubleType(),    True),
    StructField("currency",        StringType(),    True),
    StructField("event_ts",        TimestampType(), False),
])

SCHEMAS_BY_STREAM: dict[str, StructType] = {
    "employees":   EMPLOYEE_SCHEMA,
    "attendance":  ATTENDANCE_SCHEMA,
    "performance": PERFORMANCE_SCHEMA,
    "recruitment": RECRUITMENT_SCHEMA,
}
