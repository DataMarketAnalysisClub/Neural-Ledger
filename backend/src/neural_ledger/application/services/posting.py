"""Statement → transaction ledger: classify the charges (port), gate the guesses (domain), store.

The classifier is whatever adapter bootstrap registered; this service only needs one guess per
charge. A statement is posted only when it reconciles, is final (not an unbilled-movements export) and the
classifier answered; otherwise nothing reaches the ledger and a warning says why. Re-importing posts again, idempotently, so a
statement stored while the classifier was unavailable is posted once it is back.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...domain.ledger.categorization import RULE, classifiable, post_statement
from ...domain.shared.envelope import Caveat
from ...domain.statements.model import StoredStatement
from ..ports import ClassifierUnavailable, TransactionClassifier, TransactionStore


@dataclass(frozen=True, slots=True)
class PostingResult:
    posted: int  # transactions this statement contributes to the ledger
    new: int  # of those, stored by this call (0 on a re-import)
    uncategorized: int  # charges (classified lines) whose category was not accepted
    classifier: str | None  # None when nothing was posted
    warnings: tuple[Caveat, ...]


def _not_posted(reason: str) -> PostingResult:
    message = f"The statement's movements were not added to the transaction ledger: {reason}."
    return PostingResult(0, 0, 0, None, (Caveat("NOT_POSTED", message, ("not added", "ledger")),))


class LedgerPosting:
    def __init__(self, classifier: TransactionClassifier, transactions: TransactionStore) -> None:
        self._classifier = classifier
        self._transactions = transactions

    def post(self, stored: StoredStatement) -> PostingResult:
        if not stored.verified:
            return _not_posted("it does not reconcile, so its amounts are unverified")
        if stored.statement.provisional:
            return _not_posted("it lists unbilled card movements, which the billed statement will add")
        charges = classifiable(stored)
        try:
            guesses = list(self._classifier.classify([line.description for line in charges]))
        except ClassifierUnavailable as exc:
            return _not_posted(f"the classifier is unavailable ({exc}); import it again once it is back")
        if len(guesses) != len(charges):
            return _not_posted(f"the classifier answered {len(guesses)} times for {len(charges)} charges")

        posted = post_statement(stored, {line.index: g for line, g in zip(charges, guesses)}, self._classifier.name)
        new = self._transactions.add(posted)
        uncategorized = sum(1 for p in posted if not p.categorized)
        warnings = ()
        if uncategorized:
            message = f"{uncategorized} of {len(charges)} charges have no category: the classifier was not confident enough."
            warnings = (Caveat("UNCATEGORIZED_SPENDING", message, ("no category", "uncategorized")),)
        # The classifiers that actually answered (a fallback chain names only the one that did), else the configured one.
        answered = "+".join(sorted({p.classifier for p in posted if p.classifier != RULE})) or self._classifier.name
        return PostingResult(len(posted), new, uncategorized, answered, warnings)
