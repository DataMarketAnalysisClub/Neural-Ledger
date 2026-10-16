"""Classifier fallback: try the primary classifier, fall back to the next one (ADR-032: jev, then naive Bayes).

One classifier answers a whole statement, never a mix within one call: Jev fails as a batch, so the
statement is categorized by the next classifier in order. Every guess carries the classifier that made
it as its source, so each transaction records which model chose its category. If all of them are
unavailable, the statement is stored and not posted (LedgerPosting's NOT_POSTED warning).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import replace

from ...domain.ledger.categorization import CategoryGuess
from ..ports import ClassifierUnavailable, TransactionClassifier

logger = logging.getLogger(__name__)


class FallbackClassifier:
    def __init__(self, classifiers: Sequence[TransactionClassifier]) -> None:
        if not classifiers:
            raise ValueError("at least one classifier is required")
        self._classifiers = tuple(classifiers)
        self.name = "+".join(c.name for c in self._classifiers)

    def classify(self, descriptions: Sequence[str]) -> tuple[CategoryGuess, ...]:
        last_error: Exception | None = None
        for classifier in self._classifiers:
            try:
                guesses = tuple(classifier.classify(descriptions))
            except ClassifierUnavailable as exc:
                # A silent fallback looks exactly like a working classifier, so always say why.
                logger.warning("classifier %s unavailable, trying the next one: %s", classifier.name, exc)
                last_error = exc
                continue
            return tuple(g if g.source else replace(g, source=classifier.name) for g in guesses)
        raise ClassifierUnavailable(f"all classifiers failed: {last_error}")
