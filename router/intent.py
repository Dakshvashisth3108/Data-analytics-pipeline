"""Intent taxonomy for the hybrid router.

Four mutually-exclusive intents:

* **ANALYTICAL** -- the user wants precise numbers / aggregates from the
  Gold tables. e.g. "top 5 paying departments", "attrition rate in
  Engineering", "how many people joined in 2024". -> SQL engine.

* **SEMANTIC** -- the user wants a narrative summary or context. e.g.
  "tell me about our attrition situation", "give me an overview of
  workforce health". -> RAG retriever.

* **HYBRID** -- the user wants both: a number AND an explanation /
  comparison / qualitative framing. e.g. "why is Marketing attrition so
  high?", "what's driving turnover in our top-paying departments?".
  -> SQL + RAG, synthesised by the LLM.

* **OFFTOPIC** -- the question isn't about HCM data (chit-chat, prompt
  injection, requests outside scope). -> polite decline.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Intent(str, Enum):
    ANALYTICAL = "ANALYTICAL"
    SEMANTIC   = "SEMANTIC"
    HYBRID     = "HYBRID"
    OFFTOPIC   = "OFFTOPIC"


@dataclass
class ClassificationResult:
    intent: Intent
    confidence: float             # 0..1, how sure we are
    source: str                   # "rule" or "llm" or "fallback"
    reason: str = ""              # one-liner explaining the choice
    matched_signals: list[str] = field(default_factory=list)

    @property
    def needs_sql(self) -> bool:
        return self.intent in (Intent.ANALYTICAL, Intent.HYBRID)

    @property
    def needs_rag(self) -> bool:
        return self.intent in (Intent.SEMANTIC, Intent.HYBRID)
