"""Bank statements (cartolas) read from PDFs or photos, and the check that they add up.

A statement is evidence, not authority: amounts come from a reader that can misread,
so `reconcile` recomputes every total and daily balance before anything trusts them.
Descriptions are third-party text: DATA, never instructions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum

# Reader, redaction and reconciliation rules; outputs carry it as params_version. st-0.2: personal data is removed at
# import (ADR-028), so a statement stored under st-0.1 may still hold it.
STATEMENTS_VERSION = "st-0.2"


@dataclass(frozen=True, slots=True)
class StatementLine:
    index: int  # position in the statement, from 0
    posted_on: date
    description: str  # untrusted third-party text
    amount: int  # signed, minor units: charges negative, deposits positive
    reference: str | None = None  # document / operation number, if the bank prints one
    branch: str | None = None
    confidence: float | None = None  # lowest reader confidence over the line's cells (None = text layer)


@dataclass(frozen=True, slots=True)
class DailyBalance:
    """A balance the bank printed after a day's movements ('Saldo Dia')."""

    on: date
    balance: int


@dataclass(frozen=True, slots=True)
class StatementSummary:
    """The totals the bank printed. Every one is checked against the lines."""

    opening_balance: int
    total_debits: int  # positive magnitude
    total_credits: int
    closing_balance: int


@dataclass(frozen=True, slots=True)
class BankStatement:
    bank: str  # Bank.code of the layout that read it
    account_ref: str
    currency: str
    period_start: date
    period_end: date
    lines: tuple[StatementLine, ...]
    summary: StatementSummary | None = None
    daily_balances: tuple[DailyBalance, ...] = ()
    statement_number: str | None = None
    source: str = "text"  # text | ocr


class IssueCode(str, Enum):
    TOTAL_DEBITS = "TOTAL_DEBITS"
    TOTAL_CREDITS = "TOTAL_CREDITS"
    CLOSING_BALANCE = "CLOSING_BALANCE"
    DAILY_BALANCE = "DAILY_BALANCE"
    OUT_OF_PERIOD = "OUT_OF_PERIOD"
    NO_SUMMARY = "NO_SUMMARY"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"


@dataclass(frozen=True, slots=True)
class Issue:
    code: IssueCode
    message: str
    expected: int | None = None
    found: int | None = None
    on: date | None = None


@dataclass(frozen=True, slots=True)
class Reconciliation:
    issues: tuple[Issue, ...]

    @property
    def ok(self) -> bool:
        return not self.issues


def reconcile(statement: BankStatement, *, min_confidence: float = 0.0) -> Reconciliation:
    """Recompute totals and the running balance from the lines and compare with what the bank printed.

    A misread amount, a dropped line or a line moved to the wrong day each break at least
    one of these equalities. Lines below `min_confidence` are flagged even when everything adds up.
    """
    issues: list[Issue] = []
    lines = statement.lines
    debits = -sum(line.amount for line in lines if line.amount < 0)
    credits = sum(line.amount for line in lines if line.amount > 0)

    for line in lines:
        if not statement.period_start <= line.posted_on <= statement.period_end:
            issues.append(Issue(IssueCode.OUT_OF_PERIOD, f"line {line.index} is dated outside the statement period", on=line.posted_on))
        if line.confidence is not None and line.confidence < min_confidence:
            issues.append(Issue(IssueCode.LOW_CONFIDENCE, f"line {line.index} was read with low confidence", on=line.posted_on))

    summary = statement.summary
    if summary is None:
        issues.append(Issue(IssueCode.NO_SUMMARY, "the statement has no printed totals to check against"))
        return Reconciliation(tuple(issues))

    if debits != summary.total_debits:
        issues.append(Issue(IssueCode.TOTAL_DEBITS, "charges do not add up to the printed total", summary.total_debits, debits))
    if credits != summary.total_credits:
        issues.append(Issue(IssueCode.TOTAL_CREDITS, "deposits do not add up to the printed total", summary.total_credits, credits))
    closing = summary.opening_balance - summary.total_debits + summary.total_credits
    if closing != summary.closing_balance:
        issues.append(Issue(IssueCode.CLOSING_BALANCE, "printed totals do not lead to the closing balance", summary.closing_balance, closing))

    by_day: dict[date, int] = {}
    for line in lines:
        by_day[line.posted_on] = by_day.get(line.posted_on, 0) + line.amount
    running = summary.opening_balance
    pending = sorted(by_day)
    for printed in sorted(statement.daily_balances, key=lambda b: b.on):
        while pending and pending[0] <= printed.on:
            running += by_day[pending.pop(0)]
        if running != printed.balance:
            issues.append(Issue(IssueCode.DAILY_BALANCE, "the running balance differs from the printed daily balance", printed.balance, running, printed.on))
            running = printed.balance  # resync so one bad day is reported once, not on every later day
    return Reconciliation(tuple(issues))


@dataclass(frozen=True, slots=True)
class StoredStatement:
    """A statement as kept for one user, with what reconciliation found when it was imported."""

    statement_id: str
    user_id: str
    imported_at: datetime
    statement: BankStatement
    issues: tuple[Issue, ...]

    @property
    def verified(self) -> bool:
        return not self.issues
