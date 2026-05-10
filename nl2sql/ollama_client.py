"""Thin HTTP wrapper around the Ollama local REST API.

Ollama exposes /api/generate on http://localhost:11434 by default. We
talk to it directly with `requests` rather than depending on the
`ollama` Python client — fewer transitive deps, easier to audit, and
the API surface we need is tiny.

The first call also runs a health-check (`/api/version`) so the user
gets a clear "is Ollama running?" error instead of a connection refused
buried in a stack trace.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import requests

from utils import get_logger

LOG = get_logger("hcm.nl2sql.ollama")


class OllamaUnavailable(RuntimeError):
    """Raised when the Ollama server is unreachable or the model is missing."""


@dataclass
class GenerateResult:
    text: str
    model: str
    elapsed_ms: int


class OllamaClient:
    def __init__(self,
                 base_url: str = "http://localhost:11434",
                 model: str = "gemma2:2b",
                 timeout_seconds: int = 120,
                 temperature: float = 0.1,
                 num_predict: int = 512) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout_seconds
        self.temperature = float(temperature)
        self.num_predict = int(num_predict)
        self._healthy: bool | None = None

    # ── health ───────────────────────────────────────────────────────────
    def healthcheck(self) -> None:
        """Verify Ollama is up and the configured model is pulled."""
        if self._healthy:
            return
        try:
            r = requests.get(f"{self.base_url}/api/version", timeout=5)
            r.raise_for_status()
        except requests.RequestException as exc:
            raise OllamaUnavailable(
                f"Cannot reach Ollama at {self.base_url}. "
                f"Is `ollama serve` running?\n"
                f"  Install:  https://ollama.com/download\n"
                f"  Then:     ollama pull {self.model}\n"
                f"Underlying error: {exc}"
            ) from exc

        # Confirm the model is locally available
        try:
            r = requests.get(f"{self.base_url}/api/tags", timeout=10)
            r.raise_for_status()
            tags = {m.get("name", "") for m in r.json().get("models", [])}
        except (requests.RequestException, ValueError):
            tags = set()
        # Ollama tags are like "gemma2:2b". Match exact or by family root.
        if tags and self.model not in tags and not any(
            t.split(":")[0] == self.model.split(":")[0] for t in tags
        ):
            raise OllamaUnavailable(
                f"Model {self.model!r} is not pulled locally. "
                f"Run: ollama pull {self.model}"
            )
        self._healthy = True

    # ── generate ─────────────────────────────────────────────────────────
    def generate(self, prompt: str, *,
                 system: str | None = None,
                 stop: list[str] | None = None) -> GenerateResult:
        """Synchronous, non-streaming generation."""
        self.healthcheck()
        body: dict[str, Any] = {
            "model":   self.model,
            "prompt":  prompt,
            "stream":  False,
            "options": {
                "temperature": self.temperature,
                "num_predict": self.num_predict,
            },
        }
        if system:
            body["system"] = system
        if stop:
            body["options"]["stop"] = stop

        LOG.info("ollama_generate model=%s prompt_chars=%d",
                 self.model, len(prompt) + (len(system) if system else 0))
        try:
            r = requests.post(
                f"{self.base_url}/api/generate",
                json=body, timeout=self.timeout,
            )
            r.raise_for_status()
            data = r.json()
        except requests.RequestException as exc:
            LOG.exception("ollama_request_failed")
            raise OllamaUnavailable(f"Ollama request failed: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise OllamaUnavailable(
                f"Ollama returned non-JSON: {r.text[:200]!r}"
            ) from exc

        text = (data.get("response") or "").strip()
        elapsed = int(data.get("total_duration", 0) / 1_000_000)  # ns -> ms
        LOG.info("ollama_generated chars=%d elapsed_ms=%d", len(text), elapsed)
        return GenerateResult(text=text, model=self.model, elapsed_ms=elapsed)
