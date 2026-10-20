"""A relevance floor per index (ADR-040): lexical and embedding scores are on different scales.

Each index in the chain is wrapped with its own floor before the fallback, so whichever index answers, a passage
below that index's floor never reaches the explanation. The use case then keeps passages as they come
(min_score 0). Floors are tuned on tests/rag_eval, never chosen by feel.
"""

from __future__ import annotations

from collections.abc import Sequence

from ...domain.education.concepts import Passage
from ..ports import KnowledgeBase


class ThresholdKnowledgeBase:
    def __init__(self, inner: KnowledgeBase, min_score: float) -> None:
        if not 0 <= min_score <= 1:
            raise ValueError("min_score must be in [0, 1]")
        self._inner = inner
        self.min_score = min_score
        self.name = inner.name

    def search(self, query: str, lang: str, k: int) -> Sequence[Passage]:
        return tuple(p for p in self._inner.search(query, lang, k) if p.score >= self.min_score)
