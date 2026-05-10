"""Rolling-window conversation memory.

The router passes a short slice of recent turns into the LLM prompt
(classification + synthesis) so follow-up questions like "why is it so
high?" can resolve "it" from prior context. We only keep the question
and a short answer summary -- not full SQL rows or RAG chunks -- to
stay well inside Gemma 2B's modest context window.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Iterable


@dataclass
class Turn:
    question: str
    answer_summary: str    # short, prompt-safe summary of what we replied
    intent: str = ""       # the routing decision for this turn (audit)


class Conversation:
    def __init__(self, max_turns: int = 6) -> None:
        self.max_turns = int(max_turns)
        self._turns: deque[Turn] = deque(maxlen=self.max_turns)

    def add(self, turn: Turn) -> None:
        self._turns.append(turn)

    def clear(self) -> None:
        self._turns.clear()

    def turns(self) -> list[Turn]:
        return list(self._turns)

    def recent_pairs(self, n: int = 3) -> list[tuple[str, str]]:
        """Most recent (question, answer_summary) tuples, oldest first."""
        if n <= 0:
            return []
        slice_ = list(self._turns)[-n:]
        return [(t.question, t.answer_summary) for t in slice_]

    def render(self, n: int = 3, max_chars_per_turn: int = 300) -> str:
        """Render recent context as a prompt-friendly block."""
        pairs = self.recent_pairs(n)
        if not pairs:
            return ""
        lines = ["Recent conversation:"]
        for q, a in pairs:
            q = q.strip().replace("\n", " ")[:max_chars_per_turn]
            a = a.strip().replace("\n", " ")[:max_chars_per_turn]
            lines.append(f"  User: {q}")
            lines.append(f"  Assistant: {a}")
        return "\n".join(lines)
