"""Read the transaction ledger built from imported statements, with spend totals per category.

Totals are computed here from stored integers; the category labels came from a classifier and
were gated by the domain. Merchant text leaves this layer wrapped as untrusted text.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from ...domain.agent.untrusted import wrap_untrusted
from ...domain.ledger.categorization import CATEGORIZATION_VERSION, PostedTransaction
from ...domain.ledger.entities import TransactionKind
from ...domain.shared.envelope import Envelope, Fact
from ...domain.shared.hashing import content_id
from ..ports import TransactionStore


@dataclass(frozen=True, slots=True)
class TransactionView:
    txn_id: str
    account_id: str
    date: str
    amount: int  # signed minor units of `currency`; charges are negative
    currency: str
    merchant: dict[str, str]  # {"untrusted_text": ...}
    kind: str
    category: str
    classifier: str
    confidence: float | None
    statement_id: str
    line_index: int


@dataclass(frozen=True, slots=True)
class CategoryTotalView:
    category: str
    currency: str
    spent: int  # positive magnitude of the charges in this category
    count: int


@dataclass(frozen=True, slots=True)
class TransactionList:
    transactions: tuple[TransactionView, ...]
    spending: tuple[CategoryTotalView, ...]  # by currency, then largest spend first
    income: tuple[CategoryTotalView, ...]  # one row per currency, category "income"


class LedgerUseCases:
    def __init__(self, transactions: TransactionStore) -> None:
        self._transactions = transactions

    def list_transactions(self, user_id: str) -> Envelope[TransactionList]:
        posted = self._transactions.for_user(user_id)
        spending = _totals(p for p in posted if p.transaction.kind is TransactionKind.PURCHASE)
        income = _totals(p for p in posted if p.transaction.kind is TransactionKind.INCOME)
        facts = [Fact(f"{user_id}.transactions", len(posted), "count", "transactions in the ledger from imported statements")]
        for t in spending:
            facts.append(Fact(f"{user_id}.spending.{t.currency}.{t.category}", t.spent, t.currency, f"sum of {t.count} charges"))
        for t in income:
            facts.append(Fact(f"{user_id}.income.{t.currency}", t.spent, t.currency, f"sum of {t.count} deposits"))
        return Envelope.success(
            TransactionList(tuple(_view(p) for p in posted), spending, income),
            params_version=CATEGORIZATION_VERSION,
            snapshot_id=content_id("txns", user_id, [(p.transaction.txn_id, p.transaction.category) for p in posted]),
            as_of=max((p.transaction.date.isoformat() for p in posted), default=""),
            facts=tuple(facts),
        )


def _totals(posted) -> tuple[CategoryTotalView, ...]:
    sums: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    for p in posted:
        entry = sums[(p.currency, p.transaction.category)]
        entry[0] += abs(p.transaction.amount)
        entry[1] += 1
    rows = [CategoryTotalView(category, currency, spent, count) for (currency, category), (spent, count) in sums.items()]
    return tuple(sorted(rows, key=lambda r: (r.currency, -r.spent, r.category)))


def _view(p: PostedTransaction) -> TransactionView:
    t = p.transaction
    return TransactionView(
        txn_id=t.txn_id,
        account_id=t.account_id,
        date=t.date.isoformat(),
        amount=t.amount,
        currency=p.currency,
        merchant=wrap_untrusted(t.merchant_raw),
        kind=t.kind.value,
        category=t.category,
        classifier=p.classifier,
        confidence=p.confidence,
        statement_id=p.statement_id,
        line_index=p.line_index,
    )
