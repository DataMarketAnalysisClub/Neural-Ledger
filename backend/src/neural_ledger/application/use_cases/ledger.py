"""Read the transaction ledger built from imported statements, with spend totals per category, and let the user
set a transaction's category (ADR-023).

Totals are computed here from stored integers; the category labels came from a classifier and were gated by
the domain, or from the user. Merchant text leaves this layer wrapped as untrusted text. Setting a category is
a UI route only, never an agent tool.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from ...domain.agent.untrusted import wrap_untrusted
from ...domain.audit.events import Actor, AuditDraft, AuditKind
from ...domain.ledger.categorization import CATEGORIZATION_VERSION, MOVEMENT, PostedTransaction, relabel, user_categories
from ...domain.ledger.entities import InstallmentInfo, TransactionKind
from ...domain.shared.envelope import Envelope, Fact
from ...domain.shared.hashing import content_id
from ..ports import Clock, IdGenerator, TransactionStore, TransactionWrites


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
    installment: InstallmentView | None


@dataclass(frozen=True, slots=True)
class InstallmentView:
    plan_id: str
    installment_number: int
    installment_total: int
    original_amount: int
    monthly_rate: float | None


@dataclass(frozen=True, slots=True)
class CategoryTotalView:
    category: str
    currency: str
    spent: int  # spending: charges and fees less refunds, positive when money went out; income: deposits
    count: int


@dataclass(frozen=True, slots=True)
class TransactionList:
    transactions: tuple[TransactionView, ...]
    spending: tuple[CategoryTotalView, ...]  # by currency, then largest spend first
    income: tuple[CategoryTotalView, ...]  # one row per currency, category "income"


class LedgerUseCases:
    def __init__(self, transactions: TransactionStore, writes: TransactionWrites, clock: Clock, ids: IdGenerator) -> None:
        self._transactions = transactions
        self._writes = writes
        self._clock = clock
        self._ids = ids

    def list_transactions(self, user_id: str) -> Envelope[TransactionList]:
        posted = self._transactions.for_user(user_id)
        # Movimientos are the holder's own money moving (card payments by rule, anything else the user marks, ADR-024):
        # neither spending nor income.
        spending = _totals((p for p in posted if p.transaction.kind in SPENDING_KINDS and not _movement(p)), sign=-1)
        income = _totals((p for p in posted if p.transaction.kind is TransactionKind.INCOME and not _movement(p)), sign=1)
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


    def set_category(self, user_id: str, session_id: str, txn_id: str, category: str) -> Envelope[TransactionView]:
        """The user's category wins over any model and survives re-imports, which keep a stored category.

        The kind and amount never change; a category the kind cannot take is INVALID_INPUT with the allowed ones.
        """
        current = self._transactions.get(user_id, txn_id)
        if current is None:
            return Envelope.insufficient(("transaction",), params_version=CATEGORIZATION_VERSION, message="no such transaction for this user")
        updated = relabel(current, category)
        if updated is None:
            allowed = tuple(sorted(user_categories(current.transaction.kind)))
            return Envelope.invalid("category", allowed, params_version=CATEGORIZATION_VERSION, message=f"a {current.transaction.kind.value} can take only these categories")
        draft = AuditDraft(
            event_id=self._ids.new("evt"),
            timestamp=self._clock.now(),
            session_id=session_id,
            actor=Actor.USER,
            kind=AuditKind.CATEGORY_CHANGED,
            forecast_snapshot_id=txn_id,
            policy_version=CATEGORIZATION_VERSION,
            detail=f"from={current.transaction.category} to={category} previous_classifier={current.classifier}",
            user_id=user_id,
        )
        if not self._writes.update_transaction(current, updated, (draft,)):  # the change and its audit event, or neither
            return Envelope.invalid("transaction", (), params_version=CATEGORIZATION_VERSION, message="transaction changed; reload and retry")
        return Envelope.success(
            _view(updated),
            params_version=CATEGORIZATION_VERSION,
            snapshot_id=content_id("txn", user_id, txn_id, category),
            as_of=updated.transaction.date.isoformat(),
        )


SPENDING_KINDS = frozenset({TransactionKind.PURCHASE, TransactionKind.FEE, TransactionKind.REFUND})


def _movement(p: PostedTransaction) -> bool:
    return p.transaction.category == MOVEMENT


def _totals(posted, sign: int) -> tuple[CategoryTotalView, ...]:
    sums: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    for p in posted:
        entry = sums[(p.currency, p.transaction.category)]
        entry[0] += sign * p.transaction.amount
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
        installment=_installment(t.installment),
    )


def _installment(info: InstallmentInfo | None) -> InstallmentView | None:
    if info is None:
        return None
    rate = float(info.monthly_rate) if info.monthly_rate is not None else None
    return InstallmentView(info.plan_id, info.installment_number, info.installment_total, info.original_amount, rate)
