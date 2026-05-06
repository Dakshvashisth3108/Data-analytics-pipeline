"""Unit tests for Silver transformations — pure DataFrame->DataFrame logic."""
from __future__ import annotations

from datetime import datetime, date

from silver.build_silver_attendance  import transform as t_attendance
from silver.build_silver_employees   import transform as t_employees
from silver.build_silver_performance import transform as t_performance


def test_attendance_invalid_hours_become_null(spark):
    df = spark.createDataFrame([
        ("a1", "E1", date(2026, 5, 1), None, None, 27.5, "present", "none", False, datetime.utcnow()),
        ("a2", "E2", date(2026, 5, 1), None, None,  8.0, "present", "none", False, datetime.utcnow()),
    ], ["attendance_id","employee_id","work_date","punch_in","punch_out",
         "hours_worked","status","leave_type","is_late","event_ts"])
    out = t_attendance(df).collect()
    by_id = {r["attendance_id"]: r for r in out}
    assert by_id["a1"]["hours_worked"] is None
    assert by_id["a2"]["hours_worked"] == 8.0


def test_performance_filters_invalid_ratings(spark):
    df = spark.createDataFrame([
        ("r1","E1","2026-H1", 4,"Exceeds", 90.0,"M1","ok",True,  10000.0, datetime.utcnow()),
        ("r2","E2","2026-H1", 9,"x",      90.0,"M1","ok",False,     0.0, datetime.utcnow()),
    ], ["review_id","employee_id","cycle","rating","rating_label","goals_met_pct",
         "reviewer_id","comments","promotion_flag","bonus_amount","event_ts"])
    out = t_performance(df).collect()
    assert {r["review_id"] for r in out} == {"r1"}


def test_employees_marks_current_record(spark):
    df = spark.createDataFrame([
        ("E1","A","B","a@x","M",None,None,None,"Eng","SDE","L3",None,"BLR","IN","FT",
         100000.0,"INR",True,  datetime(2026,1,1)),
        ("E1","A","B","a@x","M",None,None,None,"Eng","SDE-2","L3",None,"BLR","IN","FT",
         110000.0,"INR",True,  datetime(2026,4,1)),
    ], ["employee_id","first_name","last_name","email","gender","date_of_birth","hire_date",
         "termination_date","department","job_title","grade","manager_id","location","country",
         "employment_type","base_salary","currency","is_active","event_ts"])
    out = {(r["employee_id"], r["job_title"]): r["is_current"] for r in t_employees(df).collect()}
    assert out[("E1","SDE")]   is False
    assert out[("E1","SDE-2")] is True
