"""Post a verified bank statement into the ledger: one Transaction per statement line.

Everything here is deterministic. The only model input is a CategoryGuess per charge, and it
is gated: a label outside CATEGORIES or below the confidence floor becomes 'uncategorized'.
A category is a label for spend breakdowns, never an amount, a kind or a permission; amounts
and kinds come from the reconciled statement alone.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

from ..shared.hashing import content_id
from ..statements.model import StoredStatement
from .entities import Transaction, TransactionKind

CATEGORIZATION_VERSION = "cat-0.1"  # posting rules + vocabulary; outputs carry it as params_version

# Spending categories a classifier may choose. The first six are the personas' categories.
CATEGORIES = frozenset({"groceries", "dining", "health", "shopping", "transport", "utilities", "entertainment", "other"})
INCOME = "income"
UNCATEGORIZED = "uncategorized"
# Naive Bayes over 8 classes gives ~0.2 to merchants it has never seen and 0.7+ to ones it has.
MIN_CATEGORY_CONFIDENCE = 0.5
RULE = "rule"  # classifier name recorded when a rule, not a model, chose the category


@dataclass(frozen=True, slots=True)
class CategoryGuess:
    """A classifier's answer for one description. Untrusted until post_statement gates it."""

    category: str
    confidence: float

    def __post_init__(self) -> None:
        if not (math.isfinite(self.confidence) and 0.0 <= self.confidence <= 1.0):
            raise ValueError(f"confidence must be in [0, 1], got {self.confidence!r}")


@dataclass(frozen=True, slots=True)
class PostedTransaction:
    """A ledger transaction with where it came from and how its category was chosen."""

    user_id: str
    currency: str
    transaction: Transaction
    statement_id: str
    line_index: int
    classifier: str  # the method that chose the category ("rule" for income)
    confidence: float | None  # the model's confidence, also when it was too low to accept

    @property
    def categorized(self) -> bool:
        return self.transaction.category != UNCATEGORIZED


def accept(guess: CategoryGuess | None, min_confidence: float = MIN_CATEGORY_CONFIDENCE) -> str:
    if guess is None or guess.category not in CATEGORIES or guess.confidence < min_confidence:
        return UNCATEGORIZED
    return guess.category


def post_statement(
    stored: StoredStatement,
    guesses: Mapping[int, CategoryGuess],
    classifier: str,
    *,
    min_confidence: float = MIN_CATEGORY_CONFIDENCE,
) -> tuple[PostedTransaction, ...]:
    """Charges become purchases categorized by `guesses` (keyed by line index); deposits become income.

    Only a statement that reconciles is posted: an unverified amount must not reach the ledger
    the financial core computes from.
    """
    if not stored.verified:
        raise ValueError("only a verified statement can be posted to the ledger")
    s = stored.statement
    account_id = f"{s.bank}:{s.account_ref}"
    posted = []
    for line in s.lines:
        if line.amount > 0:
            kind, category, method, confidence = TransactionKind.INCOME, INCOME, RULE, None
        else:
            guess = guesses.get(line.index)
            kind, category, method = TransactionKind.PURCHASE, accept(guess, min_confidence), classifier
            confidence = guess.confidence if guess else None
        txn = Transaction(
            txn_id=content_id("txn", stored.user_id, stored.statement_id, line.index),
            account_id=account_id,
            date=line.posted_on,
            amount=line.amount,
            merchant_raw=line.description,
            category=category,
            kind=kind,
        )
        posted.append(PostedTransaction(stored.user_id, s.currency, txn, stored.statement_id, line.index, method, confidence))
    return tuple(posted)
