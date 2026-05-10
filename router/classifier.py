"""Two-tier intent classifier.

Tier 1 -- **rules**:  microsecond keyword/regex heuristics. If a
question clearly fits one bucket (e.g. starts with "show me top 5..."
-> ANALYTICAL), we return immediately without an LLM call.

Tier 2 -- **LLM**:  if rules are ambiguous, we ask Gemma 2B via Ollama
to classify. The LLM call adds ~300-500ms but handles the genuinely
hard cases (follow-up questions, mixed intent, etc.).

The two tiers share a ``ClassificationResult`` schema so downstream
code can't tell which path produced the answer except by reading
``.source``.
"""
from __future__ import annotations

import re
from typing import Iterable

from utils import get_logger

from .conversation import Conversation
from .intent import ClassificationResult, Intent

LOG = get_logger("hcm.router.classifier")


# ── Tier 1 rules ─────────────────────────────────────────────────────────
# Patterns are case-insensitive. Each tuple = (regex, intent, weight).
# Weights stack; a question scoring >= 2 in one bucket and 0 in the others
# is considered "clearly" that intent.
_RULES: list[tuple[str, Intent, int]] = [
    # ANALYTICAL: aggregates, top-N, comparisons, numeric asks
    (r"\btop\s+\d+\b",                        Intent.ANALYTICAL, 2),
    (r"\bbottom\s+\d+\b",                     Intent.ANALYTICAL, 2),
    (r"\bhow many\b",                         Intent.ANALYTICAL, 2),
    (r"\bcount of\b",                         Intent.ANALYTICAL, 2),
    (r"\b(highest|lowest|max(imum)?|min(imum)?)\b", Intent.ANALYTICAL, 2),
    (r"\b(average|avg|median|mean|sum|total)\b",     Intent.ANALYTICAL, 2),
    (r"\b(rank|sort|order by|list)\b",        Intent.ANALYTICAL, 1),
    (r"\b(rate|ratio|percentage|pct|%)\b",    Intent.ANALYTICAL, 1),
    (r"\bcompare\b",                          Intent.ANALYTICAL, 1),
    (r"\bbreak[\- ]?down\b",                  Intent.ANALYTICAL, 1),

    # SEMANTIC: narrative, descriptive, qualitative
    (r"\b(tell me about|describe|summari[sz]e)\b", Intent.SEMANTIC, 2),
    (r"\b(give me an overview|what.?s the situation)\b", Intent.SEMANTIC, 2),
    (r"\bwhat should I know\b",               Intent.SEMANTIC, 2),
    (r"\b(narrative|story|context|background)\b", Intent.SEMANTIC, 1),
    (r"\bin general\b",                       Intent.SEMANTIC, 1),

    # HYBRID: "why" + qualitative-quantitative blend
    (r"\bwhy\s+(is|are|do|does|did)\b",       Intent.HYBRID, 2),
    (r"\bwhat\s+(is|are|'s|s)?\s*driving\b",  Intent.HYBRID, 2),
    (r"\bwhat\s+(is|are|'s|s)?\s*causing\b",  Intent.HYBRID, 2),
    (r"\b(driving|causing|leading\s+to|behind)\s+(the\s+)?"
     r"(attrition|turnover|churn|departures?|exits?|drop|spike|surge)\b",
                                              Intent.HYBRID, 2),
    (r"\b(explain|reason for|root cause)\b",  Intent.HYBRID, 2),
    (r"\b(insight|takeaway|implication)s?\b", Intent.HYBRID, 1),

    # OFFTOPIC: greetings / chit-chat / unrelated
    (r"^\s*(hi|hello|hey|yo|good (morning|afternoon|evening))[\s!.?]*$",
     Intent.OFFTOPIC, 3),
    (r"\b(weather|joke|recipe|movie|football|cricket|stock price)\b",
     Intent.OFFTOPIC, 2),
]

_HCM_KEYWORDS = (
    "employee", "employees", "headcount", "attrition", "turnover",
    "salary", "salaries", "payroll", "pay", "compensation", "comp",
    "department", "departments", "dept", "country", "countries",
    "performance", "rating", "ratings", "hire", "hires", "hiring",
    "tenure", "experience", "workforce", "team", "talent",
)


def _signals_to_intent(scores: dict[Intent, int]) -> tuple[Intent, float, list[str]]:
    """Resolve a score dict into a (intent, confidence, evidence) tuple."""
    total = sum(scores.values())
    if total == 0:
        return Intent.SEMANTIC, 0.0, []  # caller will likely defer to LLM
    best, best_score = max(scores.items(), key=lambda kv: kv[1])
    confidence = best_score / max(total, 1)
    return best, confidence, []


class IntentClassifier:
    def __init__(self, ollama_client=None,
                 enable_rule_tier: bool = True,
                 enable_llm_tier: bool = True,
                 rule_confidence_threshold: float = 0.75) -> None:
        self.ollama = ollama_client
        self.enable_rule_tier = enable_rule_tier
        self.enable_llm_tier  = enable_llm_tier and ollama_client is not None
        self.rule_threshold   = rule_confidence_threshold

    # ── tier 1 ───────────────────────────────────────────────────────────
    def _classify_rule(self, question: str) -> ClassificationResult:
        q = question.strip().lower()
        scores: dict[Intent, int] = {i: 0 for i in Intent}
        matched: list[str] = []
        for pattern, intent, weight in _RULES:
            if re.search(pattern, q, flags=re.IGNORECASE):
                scores[intent] += weight
                matched.append(f"{pattern}->{intent.value}+{weight}")

        # If no HCM keyword and no signal, lean OFFTOPIC
        if not any(kw in q for kw in _HCM_KEYWORDS) and sum(scores.values()) == 0:
            return ClassificationResult(
                intent=Intent.OFFTOPIC, confidence=0.6,
                source="rule",
                reason="No HCM keyword present and no analytical signal.",
                matched_signals=[],
            )

        intent, conf, _ = _signals_to_intent(scores)
        return ClassificationResult(
            intent=intent, confidence=conf, source="rule",
            reason=f"rule-based scores {dict((k.value, v) for k, v in scores.items() if v)}",
            matched_signals=matched,
        )

    # ── tier 2 ───────────────────────────────────────────────────────────
    _LLM_SYSTEM = (
        "You classify HR analytics questions into one of four intents. "
        "Answer with exactly one of: ANALYTICAL | SEMANTIC | HYBRID | OFFTOPIC. "
        "Then on a new line, give a one-sentence reason.\n\n"
        "Definitions:\n"
        "- ANALYTICAL: needs precise numbers/aggregates from a table.\n"
        "- SEMANTIC: needs a narrative summary or qualitative context.\n"
        "- HYBRID: needs BOTH numbers AND a narrative reason ('why' questions).\n"
        "- OFFTOPIC: not about HR / workforce / company data."
    )

    def _classify_llm(self, question: str,
                      history: Conversation | None) -> ClassificationResult:
        history_block = ""
        if history is not None:
            recent = history.recent_pairs(2)
            if recent:
                history_block = "Recent conversation:\n" + "\n".join(
                    f"- prev Q: {q}" for q, _ in recent
                ) + "\n\n"
        user_prompt = f"{history_block}Question: {question.strip()}\nIntent:"
        try:
            gen = self.ollama.generate(user_prompt, system=self._LLM_SYSTEM)
        except Exception:
            LOG.exception("llm_classify_failed")
            return ClassificationResult(
                intent=Intent.SEMANTIC, confidence=0.3,
                source="fallback",
                reason="LLM classifier failed; defaulting to SEMANTIC.",
            )

        text = (gen.text or "").strip()
        head, _, rest = text.partition("\n")
        token = head.strip().upper().strip(" .:")
        try:
            intent = Intent(token)
        except ValueError:
            # Soft match -- pick whichever intent appears first in the text
            up = text.upper()
            for cand in (Intent.HYBRID, Intent.ANALYTICAL, Intent.SEMANTIC, Intent.OFFTOPIC):
                if cand.value in up:
                    intent = cand
                    break
            else:
                intent = Intent.SEMANTIC
        return ClassificationResult(
            intent=intent, confidence=0.8, source="llm",
            reason=(rest.strip() or text)[:240],
        )

    # ── public ──────────────────────────────────────────────────────────
    def classify(self, question: str,
                 history: Conversation | None = None) -> ClassificationResult:
        if self.enable_rule_tier:
            r = self._classify_rule(question)
            # OFFTOPIC from rules with a real signal => trust it (cheap reject)
            if r.intent is Intent.OFFTOPIC and r.confidence >= 0.6:
                LOG.info("classified intent=%s conf=%.2f via=rule",
                         r.intent.value, r.confidence)
                return r
            if r.confidence >= self.rule_threshold:
                LOG.info("classified intent=%s conf=%.2f via=rule",
                         r.intent.value, r.confidence)
                return r

        if self.enable_llm_tier:
            l = self._classify_llm(question, history)
            LOG.info("classified intent=%s conf=%.2f via=%s",
                     l.intent.value, l.confidence, l.source)
            return l

        # Last resort
        out = self._classify_rule(question) if self.enable_rule_tier else \
            ClassificationResult(Intent.SEMANTIC, 0.2, "fallback",
                                 "no classifiers available; defaulting to SEMANTIC")
        LOG.info("classified intent=%s conf=%.2f via=%s",
                 out.intent.value, out.confidence, out.source)
        return out
