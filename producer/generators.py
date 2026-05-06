"""Synthetic HCM event generators.

Each generator yields dicts that conform to the Spark schemas in
``schemas/hcm_schemas.py``. Use a fixed seed for reproducibility.
"""
from __future__ import annotations

import random
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Iterator

from faker import Faker

DEPARTMENTS = ["Engineering", "Sales", "Marketing", "Finance", "HR", "Operations", "Support"]
LOCATIONS   = ["Bangalore", "Mumbai", "Delhi", "Hyderabad", "Pune", "Chennai", "Remote"]
GRADES      = ["L1", "L2", "L3", "L4", "L5", "L6", "L7"]
EMP_TYPES   = ["FT", "PT", "Contract"]
JOB_TITLES  = {
    "Engineering": ["SDE-1", "SDE-2", "SDE-3", "EM", "Architect"],
    "Sales":       ["AE", "SE", "Manager", "Director"],
    "Marketing":   ["Analyst", "Manager", "Lead"],
    "Finance":     ["Analyst", "Controller", "Manager"],
    "HR":          ["HRBP", "Recruiter", "Manager"],
    "Operations":  ["Analyst", "Manager", "Director"],
    "Support":     ["Agent", "Lead", "Manager"],
}
SOURCES = ["referral", "linkedin", "naukri", "career_site", "agency"]
STAGES  = ["applied", "screen", "interview", "offer", "hired", "rejected"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: date | datetime | None) -> str | None:
    return d.isoformat() if d else None


class HcmGenerator:
    """Stateful generator — keeps a roster of employees so attendance and
    performance events reference real ``employee_id``s."""

    def __init__(self, seed: int = 42, roster_size: int = 500) -> None:
        self.rng = random.Random(seed)
        self.faker = Faker("en_IN")
        Faker.seed(seed)
        self.roster: list[dict] = [self._new_employee() for _ in range(roster_size)]

    # ── employees ────────────────────────────────────────────────────────────
    def _new_employee(self) -> dict:
        dept = self.rng.choice(DEPARTMENTS)
        hire = self.faker.date_between(start_date="-8y", end_date="today")
        terminated = self.rng.random() < 0.08
        term_date = self.faker.date_between(start_date=hire, end_date="today") if terminated else None
        return {
            "employee_id":    f"E{self.rng.randint(100000, 999999)}",
            "first_name":     self.faker.first_name(),
            "last_name":      self.faker.last_name(),
            "email":          self.faker.unique.email(),
            "gender":         self.rng.choice(["M", "F", "O"]),
            "date_of_birth":  _iso(self.faker.date_of_birth(minimum_age=22, maximum_age=60)),
            "hire_date":      _iso(hire),
            "termination_date": _iso(term_date),
            "department":     dept,
            "job_title":      self.rng.choice(JOB_TITLES[dept]),
            "grade":          self.rng.choice(GRADES),
            "manager_id":     f"E{self.rng.randint(100000, 999999)}",
            "location":       self.rng.choice(LOCATIONS),
            "country":        "IN",
            "employment_type":self.rng.choice(EMP_TYPES),
            "base_salary":    round(self.rng.uniform(400_000, 6_000_000), 2),
            "currency":       "INR",
            "is_active":      term_date is None,
            "event_ts":       _iso(_now()),
        }

    def employees(self) -> Iterator[dict]:
        while True:
            emp = self.rng.choice(self.roster).copy()
            # Simulate field updates over time
            if self.rng.random() < 0.10:
                emp["job_title"] = self.rng.choice(JOB_TITLES[emp["department"]])
            if self.rng.random() < 0.05:
                emp["base_salary"] = round(emp["base_salary"] * self.rng.uniform(1.02, 1.20), 2)
            emp["event_ts"] = _iso(_now())
            yield emp

    # ── attendance ───────────────────────────────────────────────────────────
    def attendance(self) -> Iterator[dict]:
        while True:
            emp = self.rng.choice(self.roster)
            work_date = date.today() - timedelta(days=self.rng.randint(0, 30))
            status = self.rng.choices(
                ["present", "absent", "leave", "wfh"],
                weights=[0.7, 0.05, 0.1, 0.15],
            )[0]
            punch_in = punch_out = None
            hours = 0.0
            if status in {"present", "wfh"}:
                punch_in_dt = datetime.combine(work_date, datetime.min.time(), tzinfo=timezone.utc) \
                              + timedelta(hours=9, minutes=self.rng.randint(-30, 90))
                hours = round(self.rng.uniform(7.5, 10.5), 2)
                punch_out_dt = punch_in_dt + timedelta(hours=hours)
                punch_in, punch_out = _iso(punch_in_dt), _iso(punch_out_dt)
            yield {
                "attendance_id": str(uuid.uuid4()),
                "employee_id":   emp["employee_id"],
                "work_date":     _iso(work_date),
                "punch_in":      punch_in,
                "punch_out":     punch_out,
                "hours_worked":  hours,
                "status":        status,
                "leave_type":    self.rng.choice(["casual", "sick", "earned"]) if status == "leave" else "none",
                "is_late":       (punch_in is not None) and self.rng.random() < 0.15,
                "event_ts":      _iso(_now()),
            }

    # ── performance ──────────────────────────────────────────────────────────
    def performance(self) -> Iterator[dict]:
        cycles = ["2025-H1", "2025-H2", "2026-H1"]
        labels = {1: "Needs Improvement", 2: "Below", 3: "Meets", 4: "Exceeds", 5: "Outstanding"}
        while True:
            emp = self.rng.choice(self.roster)
            rating = self.rng.choices([1, 2, 3, 4, 5], weights=[0.05, 0.10, 0.55, 0.22, 0.08])[0]
            yield {
                "review_id":      str(uuid.uuid4()),
                "employee_id":    emp["employee_id"],
                "cycle":          self.rng.choice(cycles),
                "rating":         rating,
                "rating_label":   labels[rating],
                "goals_met_pct":  round(self.rng.uniform(40, 120), 2),
                "reviewer_id":    emp["manager_id"],
                "comments":       self.faker.sentence(nb_words=12),
                "promotion_flag": rating >= 4 and self.rng.random() < 0.3,
                "bonus_amount":   round(self.rng.uniform(0, 300_000), 2) if rating >= 3 else 0.0,
                "event_ts":       _iso(_now()),
            }

    # ── recruitment ──────────────────────────────────────────────────────────
    def recruitment(self) -> Iterator[dict]:
        while True:
            dept = self.rng.choice(DEPARTMENTS)
            stage = self.rng.choices(
                STAGES,
                weights=[0.35, 0.20, 0.20, 0.10, 0.05, 0.10],
            )[0]
            offer = round(self.rng.uniform(500_000, 5_000_000), 2) if stage in {"offer", "hired"} else None
            yield {
                "application_id": str(uuid.uuid4()),
                "requisition_id": f"R{self.rng.randint(1000, 9999)}",
                "candidate_id":   f"C{self.rng.randint(100000, 999999)}",
                "source":         self.rng.choice(SOURCES),
                "stage":          stage,
                "department":     dept,
                "job_title":      self.rng.choice(JOB_TITLES[dept]),
                "location":       self.rng.choice(LOCATIONS),
                "recruiter_id":   f"E{self.rng.randint(100000, 999999)}",
                "offer_amount":   offer,
                "currency":       "INR" if offer else None,
                "event_ts":       _iso(_now()),
            }

    def stream(self, name: str) -> Iterator[dict]:
        return {
            "employees":   self.employees,
            "attendance":  self.attendance,
            "performance": self.performance,
            "recruitment": self.recruitment,
        }[name]()
