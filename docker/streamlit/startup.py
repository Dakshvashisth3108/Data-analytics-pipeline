"""Container entrypoint — validate the environment, then launch Streamlit.

This script is the container's main process. It performs **non-fatal**
startup checks (logs warnings, never blocks the UI from starting) and
then ``exec``'s the Streamlit server so Streamlit becomes the process
that receives Docker's stop/kill signals directly.

Why a Python script and not a shell script:
  A .sh entrypoint is fragile on Windows hosts — Git may rewrite its
  line endings to CRLF, which the container's /bin/sh then rejects.
  Python doesn't care about line endings, so this is Windows-safe.

Checks performed:
  1. Ollama reachability at NL2SQL__OLLAMA__BASE_URL
  2. Gold parquet present under data/gold
  3. Chroma vector index present under data/vectors/chroma
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)-7s | startup | %(message)s",
)
log = logging.getLogger("startup")

APP_DIR = Path(__file__).resolve().parent


def check_ollama() -> None:
    """Probe the Ollama server. Warn (don't fail) if unreachable."""
    url = os.environ.get(
        "NL2SQL__OLLAMA__BASE_URL", "http://host.docker.internal:11434"
    ).rstrip("/")
    log.info("Ollama target: %s", url)
    try:
        import requests
        resp = requests.get(f"{url}/api/version", timeout=4)
        resp.raise_for_status()
        version = resp.json().get("version", "unknown")
        log.info("Ollama is reachable (version %s)", version)
    except Exception as exc:  # noqa: BLE001 — any failure is non-fatal
        log.warning(
            "Ollama is NOT reachable at %s (%s). The dashboard will still "
            "start; the AI Chat page degrades gracefully until Ollama is up. "
            "Make sure `ollama serve` is running on the HOST. On Windows/Mac "
            "Docker Desktop, host.docker.internal resolves to the host "
            "automatically.", url, exc,
        )


def check_data() -> None:
    """Confirm the mounted data lake has the artefacts the UI reads."""
    targets = {
        "Gold parquet marts": APP_DIR / "data" / "gold",
        "Chroma vector index": APP_DIR / "data" / "vectors" / "chroma",
    }
    for label, path in targets.items():
        try:
            present = path.exists() and any(path.iterdir())
        except Exception:
            present = False
        if present:
            log.info("%s found: %s", label, path)
        else:
            log.warning(
                "%s missing or empty at %s — mount the host's data/ folder "
                "as a volume (-v ./data/gold:/app/data/gold:ro). The "
                "dashboard will start but pages relying on it will be empty.",
                label, path,
            )


def main() -> None:
    log.info("=" * 60)
    log.info("HCM Analytics — Streamlit container starting")
    log.info("python=%s  workdir=%s", sys.version.split()[0], APP_DIR)
    log.info("=" * 60)

    check_ollama()
    check_data()

    log.info("Launching Streamlit on 0.0.0.0:8501 ...")
    # os.execvp REPLACES this process with Streamlit. Streamlit then
    # becomes PID 1's payload and receives SIGTERM/SIGINT directly, so
    # `docker stop` shuts it down cleanly.
    os.execvp("streamlit", [
        "streamlit", "run", "streamlit_dashboard/app.py",
        "--server.port=8501",
        "--server.address=0.0.0.0",
    ])


if __name__ == "__main__":
    main()
