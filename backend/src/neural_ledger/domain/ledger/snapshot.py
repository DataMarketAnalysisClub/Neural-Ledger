"""A ledger snapshot built from an account's own verified statements (ADR-029 step 2).

The stage-1 estimators read a LedgerSnapshot. For a persona it comes from a fixture file; for an account it is
built here, deterministically, from what reconciliation verified:

- Only verified, final (not provisional) CLP statements of this user, and only their posted transactions.
- `as_of` is the eve of the last payday the statements cover (the estimators accept no other day), and nothing
  after it is kept.
- The history starts at the first payday they cover, so every pay cycle in it is full: a salary is paid on
  payday and funds the cycle that starts there, so a cartola that starts on the 1st holds no salary for the
  cycle it starts in.
- Each account's balance is the one on `as_of`: its covering statement's opening balance plus the lines up to
  that day, which reconciliation already checked.
- The holder's own money moving is a `transfer_own`: a line a layout marked by rule, and any line the user
  labelled `movement` (ADR-023, ADR-024). A card payment stays a card payment. Everything else keeps its kind.
- Statements do not say whether income is a salary, so the profile is salaried with no contracted net: the
  estimators then use percentiles and warn CONTRACT_UNKNOWN.

No goals or savings buckets: no statement shows them.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import replace
from datetime import date, timedelta

from ..finance.paycycle import payday
from ..shared.errors import InsufficientData
from ..shared.month import Month
from ..statements.model import BankStatement, StoredStatement
from .categorization import MOVEMENT, PostedTransaction
from .entities import Account, IncomeProfile, IncomeType, LedgerSnapshot, Transaction, TransactionKind

CURRENCY = "CLP"  # the financial core's parameters are calibrated in CLP
LEDGER_VERSION = "statements"  # a label; the model's source version hashes the content
PAYDAY_RULE = "last_business_day"


def build_ledger_snapshot(
    user_id: str, statements: Sequence[StoredStatement], transactions: Sequence[PostedTransaction]
) -> LedgerSnapshot:
    usable = [
        s for s in statements
        if s.user_id == user_id and s.verified and not s.statement.provisional and s.statement.currency == CURRENCY
    ]
    if not usable:
        raise InsufficientData(("statements",), "import verified bank statements: the forecast needs at least 6 months of them")
    as_of = _last_eve_of_payday(max(s.statement.period_end for s in usable))
    start = _first_payday(min(s.statement.period_start for s in usable))
    if as_of < start:
        raise InsufficientData(("statements",), "the statements do not cover one full pay cycle yet (payday to payday)")

    accounts = _accounts(usable, as_of)
    kept = {a.account_id for a in accounts}
    used = {s.statement_id for s in usable}
    txns = tuple(
        _kind_for_the_estimators(p.transaction)
        for p in transactions
        if p.user_id == user_id and p.statement_id in used and p.transaction.account_id in kept
        and start <= p.transaction.date <= as_of
    )
    return LedgerSnapshot(
        user_id=user_id,
        currency=CURRENCY,
        as_of=as_of,
        ledger_version=LEDGER_VERSION,
        accounts=accounts,
        transactions=txns,
        goals=(),
        buckets=(),
        income_profile=IncomeProfile(IncomeType.SALARIED, None, PAYDAY_RULE),
    )


def _last_eve_of_payday(end: date) -> date:
    month = Month.of(end)
    eve = payday(month) - timedelta(days=1)
    return eve if eve <= end else payday(month.plus(-1)) - timedelta(days=1)


def _first_payday(start: date) -> date:
    month = Month.of(start)
    first = payday(month)
    return first if first >= start else payday(month.plus(1))


def _accounts(usable: Sequence[StoredStatement], as_of: date) -> tuple[Account, ...]:
    by_account: dict[str, list[BankStatement]] = defaultdict(list)
    for s in usable:
        by_account[f"{s.statement.bank}:{s.statement.account_ref}"].append(s.statement)  # the id posting gives its lines
    accounts = []
    for account_id, own in sorted(by_account.items()):
        covering = [s for s in own if s.period_start <= as_of]
        if not covering:
            continue  # the account starts after as_of: nothing of it is in the snapshot
        statement = max(covering, key=lambda s: s.period_start)
        accounts.append(Account(account_id, statement.account_type, _balance_on(statement, as_of, account_id), CURRENCY))
    return tuple(accounts)


def _balance_on(statement: BankStatement, as_of: date, account_id: str) -> int:
    summary = statement.summary
    if summary is not None and summary.opening_balance is not None:
        return summary.opening_balance + sum(line.amount for line in statement.lines if line.posted_on <= as_of)
    printed = [b for b in statement.daily_balances if b.on <= as_of]
    if printed:
        return max(printed, key=lambda b: b.on).balance
    if summary is not None and summary.closing_balance is not None and statement.period_end <= as_of:
        return summary.closing_balance
    raise InsufficientData((f"balance of {account_id}",), "a statement prints no balance to start the forecast from")


def _kind_for_the_estimators(txn: Transaction) -> Transaction:
    if txn.category == MOVEMENT and txn.kind is not TransactionKind.CARD_PAYMENT:
        return replace(txn, kind=TransactionKind.TRANSFER_OWN)
    return txn
