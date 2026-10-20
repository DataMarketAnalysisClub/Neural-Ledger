"""Bank movements read through an aggregator (Fintoc), turned into statements the usual import checks (ADR-047).

An aggregator reports each account's current balance and its movements, but no printed totals. So a sync becomes a
statement whose opening balance is the balance this account had at the previous sync and whose closing balance is
the balance now: reconciliation then checks that the new movements lead from one to the other, the same equality a
printed cartola is held to. The first sync has no previous balance, so its statement has no summary and stays
unverified (NO_SUMMARY): it is stored and shown, never posted. Movements are new by their id, not their date, so a
movement the bank back-dates is still read once.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from ..ledger.entities import AccountType
from ..statements.model import BankStatement, StatementLine, StatementSummary

MAX_SEEN = 5_000  # movement ids kept per account; older ones are dropped first


@dataclass(frozen=True, slots=True)
class BankMovement:
    movement_id: str
    posted_on: date
    description: str  # untrusted third-party text, raw: the import redacts it
    amount: int  # signed minor units, the holder's sign: charges negative
    reference: str | None = None


@dataclass(frozen=True, slots=True)
class BankAccount:
    account_id: str  # the aggregator's id; never shown
    account_ref: str  # the account number as the bank gives it; the import masks it
    currency: str
    balance: int  # current balance, minor units
    account_type: AccountType = AccountType.CHECKING


@dataclass(frozen=True, slots=True)
class AccountState:
    balance: int
    synced_on: date
    seen: tuple[str, ...]


def load_state(text: str | None) -> dict[str, AccountState]:
    if not text:
        return {}
    raw = json.loads(text)
    return {k: AccountState(int(v["balance"]), date.fromisoformat(v["synced_on"]), tuple(v["seen"])) for k, v in raw.get("accounts", {}).items()}


def dump_state(states: dict[str, AccountState]) -> str:
    accounts = {k: {"balance": s.balance, "synced_on": s.synced_on.isoformat(), "seen": list(s.seen)} for k, s in sorted(states.items())}
    return json.dumps({"accounts": accounts}, sort_keys=True, separators=(",", ":"))


def statement_from_sync(
    aggregator: str, account: BankAccount, movements: Sequence[BankMovement], previous: AccountState | None, today: date
) -> tuple[BankStatement | None, AccountState]:
    """The statement for the movements this account had not shown before, and its state after this sync.

    None when there is nothing new and the balance did not move. A balance that moved with no new movement still
    yields a statement with no lines, so reconciliation reports the gap instead of hiding it.
    """
    seen = set(previous.seen) if previous else set()
    fresh = sorted((m for m in movements if m.movement_id not in seen), key=lambda m: (m.posted_on, m.movement_id))
    known = list(previous.seen) if previous else []
    known.extend(m.movement_id for m in fresh)
    state = AccountState(account.balance, today, tuple(known[-MAX_SEEN:]))
    if not fresh and previous is not None and previous.balance == account.balance:
        return None, state
    if not fresh and previous is None:
        return None, state
    lines = tuple(
        StatementLine(index=i, posted_on=m.posted_on, description=m.description, amount=m.amount, reference=m.reference)
        for i, m in enumerate(fresh)
    )
    dates = [m.posted_on for m in fresh]
    start = min([*dates, previous.synced_on] if previous else dates)
    end = max([*dates, today])
    summary = StatementSummary(previous.balance, None, None, account.balance) if previous else None
    statement = BankStatement(
        bank=aggregator,
        account_ref=account.account_ref,
        currency=account.currency,
        period_start=start,
        period_end=end,
        lines=lines,
        summary=summary,
        source="api",
        account_type=account.account_type,
    )
    return statement, state
