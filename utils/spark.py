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

Windows preflight
-----------------
On Windows, Spark's Hadoop client uses ``winutils.exe`` for file
metadata and glob resolution. Without it, ``SparkSubmit`` dies during
``DependencyUtils.resolveGlobPath`` and PySpark sees only
"Java gateway process exited". We raise a clear error with install
steps before that happens.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from pyspark.sql import SparkSession

from .config import Config, load_config
from .logger import get_logger

_LOG = get_logger("hcm.utils.spark")

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


def _preflight_windows_hadoop() -> None:
    """Verify ``winutils.exe`` is reachable before starting the JVM.

    Without it, Spark crashes deep in ``DependencyUtils.resolveGlobPath``
    and PySpark only surfaces ``JAVA_GATEWAY_EXITED``. We translate that
    into a clear, actionable error.
    """
    if sys.platform != "win32":
        return

    hadoop_home = os.environ.get("HADOOP_HOME", "").strip().strip('"')
    winutils_paths: list[Path] = []
    if hadoop_home:
        winutils_paths.append(Path(hadoop_home) / "bin" / "winutils.exe")
    # Also check common default locations
    for guess in (r"C:\hadoop\bin\winutils.exe",
                  r"C:\hadoop-3.4.0\bin\winutils.exe"):
        winutils_paths.append(Path(guess))

    if any(p.is_file() for p in winutils_paths):
        # Ensure HADOOP_HOME is exported so child JVMs see it
        for p in winutils_paths:
            if p.is_file():
                home = p.parent.parent
                if not hadoop_home:
                    os.environ["HADOOP_HOME"] = str(home)
                    _LOG.info("set HADOOP_HOME=%s", home)
                bin_dir = str(home / "bin")
                if bin_dir not in os.environ.get("PATH", ""):
                    os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
                return

    raise RuntimeError(
        "Spark on Windows needs Hadoop's winutils.exe but it wasn't found.\n"
        "\n"
        "Quick install (one-time):\n"
        "  1. PowerShell:  powershell -ExecutionPolicy Bypass -File scripts\\setup_winutils.ps1\n"
        "  2. Restart your terminal so the new HADOOP_HOME / PATH take effect\n"
        "\n"
        "Or manually:\n"
        "  * Download hadoop-3.4.0/bin/{winutils.exe, hadoop.dll} from\n"
        "    https://github.com/cdarlint/winutils\n"
        "  * Place them in C:\\hadoop\\bin\\\n"
        "  * setx HADOOP_HOME \"C:\\hadoop\"\n"
        "  * Add %HADOOP_HOME%\\bin to your PATH\n"
    )


def build_spark(app_name: str | None = None, cfg: Config | None = None) -> SparkSession:
    """Build (or fetch) the SparkSession defined in ``configs/app.yaml``."""
    _ensure_jvm_compat()
    _preflight_windows_hadoop()

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
