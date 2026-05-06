"""SparkSession factory configured from ``configs/app.yaml``.

Java 26 compatibility
---------------------
Java 17 introduced strong module encapsulation; Java 24 made the change
irreversible (no more ``--enable-native-access=ALL-UNNAMED`` escape via
``Subject``). Spark needs reflective access to several JDK packages to
boot the JVM, so we set the standard ``--add-opens`` flags before the
SparkContext starts. Without these, Spark on Java 17/21/25/26 dies with
``InaccessibleObjectException`` or ``IllegalAccessError`` during init.

We set them in two places to be safe:
  * ``JAVA_TOOL_OPTIONS`` env var — picked up by every JVM the driver
    spawns, including the worker shell on local mode.
  * ``spark.driver.extraJavaOptions`` / ``spark.executor.extraJavaOptions``
    — what cluster-mode docs recommend; a no-op locally but keeps the
    config portable.
"""
from __future__ import annotations

import os

from pyspark.sql import SparkSession

from .config import Config, load_config

# Standard set of opens documented by the Spark project for JDK 17+.
# Java 24+ requires the same set; Spark 4.x + Hadoop 3.4 don't add
# anything new beyond this list.
JAVA_OPENS: list[str] = [
    "java.base/java.lang=ALL-UNNAMED",
    "java.base/java.lang.invoke=ALL-UNNAMED",
    "java.base/java.lang.reflect=ALL-UNNAMED",
    "java.base/java.io=ALL-UNNAMED",
    "java.base/java.net=ALL-UNNAMED",
    "java.base/java.nio=ALL-UNNAMED",
    "java.base/java.util=ALL-UNNAMED",
    "java.base/java.util.concurrent=ALL-UNNAMED",
    "java.base/java.util.concurrent.atomic=ALL-UNNAMED",
    "java.base/sun.nio.ch=ALL-UNNAMED",
    "java.base/sun.nio.cs=ALL-UNNAMED",
    "java.base/sun.security.action=ALL-UNNAMED",
    "java.base/sun.util.calendar=ALL-UNNAMED",
    "java.security.jgss/sun.security.krb5=ALL-UNNAMED",
]


def _java_options() -> str:
    """Build the ``--add-opens`` argument string."""
    return " ".join(f"--add-opens={o}" for o in JAVA_OPENS)


def _ensure_jvm_compat() -> None:
    """Inject JDK 17+ / 24+ / 26 compat flags before any JVM is spawned."""
    flags = _java_options()
    existing = os.environ.get("JAVA_TOOL_OPTIONS", "")
    # Only append if not already present, so re-runs don't bloat the env.
    if "--add-opens=java.base/java.lang=ALL-UNNAMED" not in existing:
        os.environ["JAVA_TOOL_OPTIONS"] = (existing + " " + flags).strip()


def build_spark(app_name: str | None = None, cfg: Config | None = None) -> SparkSession:
    """Build (or fetch) the SparkSession defined in ``configs/app.yaml``."""
    _ensure_jvm_compat()

    cfg = cfg or load_config()
    spark_cfg = cfg.spark
    java_opts = _java_options()

    builder = (
        SparkSession.builder
        .appName(app_name or spark_cfg.app_name)
        .master(spark_cfg.master)
        .config("spark.sql.shuffle.partitions", spark_cfg.shuffle_partitions)
        .config("spark.serializer", spark_cfg.serializer)
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.adaptive.enabled", "true")
        .config("spark.sql.adaptive.coalescePartitions.enabled", "true")
        # Pass the same opens through to driver + executor JVMs explicitly,
        # in case JAVA_TOOL_OPTIONS was overridden upstream.
        .config("spark.driver.extraJavaOptions",   java_opts)
        .config("spark.executor.extraJavaOptions", java_opts)
    )

    packages = cfg.get("spark.packages") or []
    if packages:
        builder = builder.config("spark.jars.packages", ",".join(packages))

    spark = builder.getOrCreate()
    spark.sparkContext.setLogLevel("WARN")
    return spark
