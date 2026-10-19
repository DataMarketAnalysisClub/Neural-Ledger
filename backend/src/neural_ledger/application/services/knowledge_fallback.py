"""Knowledge base fallback: try the primary index, fall back to the next one (ADR-039: chroma, then lexical).

One index answers a whole question, never a mix: passages from two indexes have scores on different scales.
The chain's name joins every index's name, so each explanation records the configured chain; if all of them
are unavailable, the use case says it has no card for that instead of explaining from memory.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from ...domain.education.concepts import Passage
from ..ports import KnowledgeBase, KnowledgeBaseUnavailable

logger = logging.getLogger(__name__)


class FallbackKnowledgeBase:
    def __init__(self, chain: Sequence[KnowledgeBase]) -> None:
        if not chain:
            raise ValueError("at least one knowledge base is required")
        self._chain = tuple(chain)
        self.name = "+".join(kb.name for kb in self._chain)

    def search(self, query: str, lang: str, k: int) -> Sequence[Passage]:
        last_error: Exception | None = None
        for kb in self._chain:
            try:
                return tuple(kb.search(query, lang, k))
            except KnowledgeBaseUnavailable as exc:
                # A silent fallback looks exactly like a working index, so always say why.
                logger.warning("knowledge base %s unavailable, trying the next one: %s", kb.name, exc)
                last_error = exc
        raise KnowledgeBaseUnavailable(f"all knowledge bases failed: {last_error}")
