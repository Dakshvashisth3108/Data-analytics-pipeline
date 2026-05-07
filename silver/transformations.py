"""Pure DataFrame -> DataFrame cleaning functions for the Silver employee table.

Each function in this module takes a DataFrame and returns a DataFrame.
No Spark session creation, no IO, no logging side-effects -- which makes
every transformation independently unit-testable with `pyspark.sql`
fixtures (see ``tests/test_silver_transforms.py``).

The orchestrator (``silver/build_silver_employees.py``) chains these in
order: clean -> normalize -> dedupe -> finalize.
"""
from __future__ import annotations

from pyspark.sql import DataFrame, Column
from pyspark.sql import functions as F
from pyspark.sql.window import Window

# ── Reference data ────────────────────────────────────────────────────────
# Each canonical department maps to a regex that matches every messy
# variant produced by ``scripts/generate_hcm_dataset.py``.
DEPARTMENT_PATTERNS: list[tuple[str, str]] = [
    ("Engineering",     r"^(eng|engg|engineering)\.?$"),
    ("Sales",           r"^sales(\s*(dept|team|-team))?$"),
    ("Marketing",       r"^(marketing|mktg)\.?(\s*dept)?$"),
    ("Finance",         r"^(finance|fin)\.?$|^finance\s*&\s*accounts$"),
    ("Human Resources", r"^(hr|h\.r\.|human[\s\-]*resources)$"),
    ("Operations",      r"^(ops|op|operations)\.?$"),
    ("Support",         r"^(support|cs|cust(omer)?\s*support)$"),
    ("IT",              r"^(it|i\.t\.|info(rmation)?\s*tech(nology)?)$"),
]

GARBAGE_SALARY_TOKENS = ("n/a", "unknown", "tbd", "-", "??", "null", "")

# Bounds for sanity validation. Tweak in configs/app.yaml as needed.
MIN_PLAUSIBLE_YEAR  = 1950
MIN_PERF_RATING     = 1
MAX_PERF_RATING     = 5
MIN_EXPERIENCE      = 0
MAX_EXPERIENCE      = 60
MIN_SALARY          = 0
MAX_SALARY          = 100_000_000  # ₹10 Cr ceiling


# ── 1. String hygiene ─────────────────────────────────────────────────────
def trim_string_columns(df: DataFrame, cols: list[str]) -> DataFrame:
    """Trim whitespace and convert empty strings to null."""
    out = df
    for c in cols:
        out = out.withColumn(
            c,
            F.when(F.length(F.trim(F.col(c))) == 0, None).otherwise(F.trim(F.col(c))),
        )
    return out


# ── 2. Department normalisation ───────────────────────────────────────────
def _canonical_department(col: Column) -> Column:
    """Map any known department spelling to its canonical form."""
    norm = F.lower(F.trim(col))
    expr = F.when(col.isNull(), F.lit(None).cast("string"))
    for canonical, pattern in DEPARTMENT_PATTERNS:
        expr = expr.when(norm.rlike(pattern), F.lit(canonical))
    # Anything else: preserve original (Silver never silently drops). A Gold
    # job can flag these via the ``department_canonical`` boolean.
    return expr.otherwise(col)


def normalize_department(df: DataFrame) -> DataFrame:
    return (
        df
        .withColumn("department_raw",       F.col("department"))
        .withColumn("department",           _canonical_department(F.col("department")))
        .withColumn(
            "department_canonical",
            F.col("department").isin([c for c, _ in DEPARTMENT_PATTERNS]),
        )
    )


# ── 3. Salary cleansing ───────────────────────────────────────────────────
def _clean_salary(col: Column) -> Column:
    """Convert dirty salary strings into a numeric DoubleType.

    Handles:
      * pure numbers           "4675038.58" -> 4675038.58
      * currency + commas      "$5,358,375" -> 5358375.0
      * 'k' suffix             "75k", "4144k" -> *1000
      * trailing units         "4250000.00 INR" -> 4250000.0
      * garbage / sentinel     "N/A", "TBD", "-", "" -> null
      * out-of-range           negative, > 10 Cr -> null
    """
    norm = F.lower(F.trim(col))
    # 'k' suffix path: strip non-numeric (except dot), cast, multiply by 1000
    k_value = (
        F.regexp_replace(norm, r"[^0-9.]", "").cast("double") * 1000
    )
    # Plain numeric path: strip everything except digits, dot, minus
    plain_value = F.regexp_replace(norm, r"[^0-9.\-]", "").cast("double")

    parsed = (
        F.when(col.isNull(), None)
         .when(norm.isin(*GARBAGE_SALARY_TOKENS), None)
         .when(norm.rlike(r"^[\d,. ]+\s*[kK]\s*$"), k_value)
         .otherwise(plain_value)
    )
    # Sanity bounds
    return F.when(
        (parsed >= MIN_SALARY) & (parsed <= MAX_SALARY), parsed
    ).otherwise(None)


def clean_salary(df: DataFrame) -> DataFrame:
    return (
        df
        .withColumn("salary_raw",  F.col("salary"))
        .withColumn("salary",      _clean_salary(F.col("salary")))
        .withColumn("salary_valid", F.col("salary").isNotNull())
    )


# ── 4. Date validation ────────────────────────────────────────────────────
def clean_joining_date(df: DataFrame) -> DataFrame:
    """Parse joining_date with strict ISO format. Invalid -> null.

    Spark 4.x ANSI mode makes `to_date` throw on unparseable strings,
    which would crash the whole job on a single bad row. `try_to_date`
    is the ANSI-safe equivalent that returns NULL. We additionally
    reject implausibly old (< 1950) or future-dated rows, since both
    signal source-system corruption.
    """
    parsed = F.try_to_date(F.col("joining_date"), "yyyy-MM-dd")
    today  = F.current_date()
    valid_range = (
        (F.year(parsed) >= MIN_PLAUSIBLE_YEAR)
        & (parsed <= today)
    )
    return (
        df
        .withColumn("joining_date_raw", F.col("joining_date"))
        .withColumn(
            "joining_date",
            F.when(valid_range, parsed).otherwise(None),
        )
        .withColumn("joining_date_valid", F.col("joining_date").isNotNull())
    )


# ── 5. Categorical standardisation ────────────────────────────────────────
def standardize_attrition(df: DataFrame) -> DataFrame:
    """Coerce attrition to {Yes, No, null}."""
    norm = F.lower(F.trim(F.col("attrition")))
    return df.withColumn(
        "attrition",
        F.when(norm.isin("yes", "y", "true", "1"), F.lit("Yes"))
         .when(norm.isin("no",  "n", "false", "0"), F.lit("No"))
         .otherwise(None),
    )


def standardize_country(df: DataFrame) -> DataFrame:
    """Title-case + trim country names."""
    return df.withColumn(
        "country",
        F.when(F.col("country").isNotNull(),
               F.initcap(F.trim(F.col("country"))))
         .otherwise(None),
    )


# ── 6. Skills cleanup ─────────────────────────────────────────────────────
def clean_skills(df: DataFrame) -> DataFrame:
    """Dedupe + sort the skills array; expose its size."""
    return (
        df
        .withColumn("skills",
                    F.when(F.col("skills").isNotNull(),
                           F.array_sort(F.array_distinct(F.col("skills"))))
                     .otherwise(None))
        .withColumn("skills_count",
                    F.when(F.col("skills").isNotNull(), F.size("skills"))
                     .otherwise(F.lit(0)))
    )


# ── 7. Numeric range validation ───────────────────────────────────────────
def validate_performance_rating(df: DataFrame) -> DataFrame:
    return df.withColumn(
        "performance_rating",
        F.when(
            F.col("performance_rating").between(MIN_PERF_RATING, MAX_PERF_RATING),
            F.col("performance_rating").cast("int"),
        ).otherwise(None),
    )


def validate_experience(df: DataFrame) -> DataFrame:
    return df.withColumn(
        "experience_years",
        F.when(
            F.col("experience").between(MIN_EXPERIENCE, MAX_EXPERIENCE),
            F.col("experience").cast("int"),
        ).otherwise(None),
    )


# ── 8. Deduplication (latest wins) ────────────────────────────────────────
def deduplicate_employees(df: DataFrame) -> DataFrame:
    """Drop rows with null employee_id, keep latest record per employee.

    'Latest' is defined as the row with the highest (ingest_ts, offset)
    pair -- so a re-streamed value supersedes earlier ones. This is the
    upsert primitive that future Silver jobs (SCD-2, CDC) build on.
    """
    base = df.filter(F.col("employee_id").isNotNull())

    order_cols = []
    if "ingest_ts" in df.columns:
        order_cols.append(F.col("ingest_ts").desc_nulls_last())
    if "offset" in df.columns:
        order_cols.append(F.col("offset").desc_nulls_last())

    if not order_cols:
        # Bronze metadata absent (e.g. unit tests) -- fall back to dropDuplicates
        return base.dropDuplicates(["employee_id"])

    w = Window.partitionBy("employee_id").orderBy(*order_cols)
    return (
        base
        .withColumn("_rn", F.row_number().over(w))
        .filter(F.col("_rn") == 1)
        .drop("_rn")
    )


# ── 9. Final projection ───────────────────────────────────────────────────
SILVER_COLUMNS: list[str] = [
    "employee_id",
    "name",
    "department",
    "department_raw",
    "department_canonical",
    "salary",
    "salary_raw",
    "salary_valid",
    "joining_date",
    "joining_date_raw",
    "joining_date_valid",
    "performance_rating",
    "manager",
    "attrition",
    "country",
    "skills",
    "skills_count",
    "experience_years",
    "ingest_ts",
    "ingest_date",
]


def select_silver_columns(df: DataFrame) -> DataFrame:
    """Project to the canonical Silver column set, dropping Kafka metadata
    that downstream consumers don't need."""
    keep = [c for c in SILVER_COLUMNS if c in df.columns]
    return df.select(*keep)


# ── Pipeline orchestrator ─────────────────────────────────────────────────
def transform_bronze_to_silver(bronze: DataFrame) -> DataFrame:
    """Apply all cleaning steps in order. Idempotent: rerunning is safe."""
    return (
        bronze
        .transform(lambda df: trim_string_columns(df, ["name", "manager", "country"]))
        .transform(normalize_department)
        .transform(clean_salary)
        .transform(clean_joining_date)
        .transform(standardize_attrition)
        .transform(standardize_country)
        .transform(clean_skills)
        .transform(validate_performance_rating)
        .transform(validate_experience)
        .transform(deduplicate_employees)
        .transform(select_silver_columns)
    )
