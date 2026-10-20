"""Is a declared salary in the statements? (ADR-049 §1-4). Pure and derived on every read: nothing here is stored.

Calendar: the declared pay month `p` has its expected payday `payday(p)` (last weekday, paycycle.py). Evidence is tied
to that payday, never to the credit's calendar month: a credit within `payday(p)` ± 3 business days (weekdays;
holidays ignored, F11) belongs to `p` even if it crosses into another month.

Eligible credits: positive CLP income of the user, not the holder's own money moving, on a checking or savings account
(CYCLE_ACCOUNTS), from a verified and final statement. A payday's window is *eligible* only when it has ended before
`today` and every cycle account the user imported has it fully covered. A missing statement is never a
non-compliance: the payday is not eligible, and that breaks consecutiveness. The price is deliberate: an account whose
statements stop (closed, or not imported lately) or start later leaves those paydays not eligible, because nothing
tells a closed account from a missing statement, and a salary paid into it would be read as missed. Like the ledger
snapshot, whose history also starts where every account is covered.

Matching: one credit per payday, within the tolerance of the applicable version's amount (inclusive, exact), the
smallest difference first, then the earliest date, then the lowest txn_id; a transaction never matches twice. Input
order and re-imports do not change the result. Transactions are never recategorized.

Counts and state: matches of the current version count from its effective_from. A payday without a match counts as
missed only from the chain's latest confirmation on (ADR-049 §4: a conflict lasts until the user confirms a new
version; any new version, the same amount re-confirmed included, moves that cut and clears it). Conflict: two
consecutive eligible paydays without a match. Verified: at least one match of the current version. Declared: neither.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum
from fractions import Fraction

from ..finance.paycycle import payday
from ..ledger.categorization import OWN_MONEY, PostedTransaction
from ..ledger.entities import TransactionKind
from ..ledger.snapshot import CURRENCY, CYCLE_ACCOUNTS
from ..shared.month import Month
from ..statements.model import StoredStatement
from .catalog import Declaration, applicable, chain

# The version of these verification rules, kept apart from the financial parameters: memory is saved only in this
# release, so the forecast stays fc-0.3 and nothing here is fc-0.4. A change of any SalaryRules value is a new version.
CHECKER_VERSION = "salary-check-0.1"


@dataclass(frozen=True, slots=True)
class SalaryRules:
    """The values ADR-049 proposes for fc-0.4, versioned as CHECKER_VERSION while memory has no numerical effect.
    They would join FinanceParams (and its lock) only with the numerical integration, once Roles A and E approve."""

    tolerance: Fraction = Fraction(5, 100)
    window_business_days: int = 3
    conflict_cycles: int = 2
    raise_confirm_cycles: int = 2  # matches a version needs before its own amount supports the conservative income


PROPOSED_RULES = SalaryRules()


@dataclass(frozen=True, slots=True)
class Credit:
    statement_id: str
    txn_id: str
    amount: int
    posted_on: date


@dataclass(frozen=True, slots=True)
class AccountSpan:
    """The days one statement covers on one cycle account."""

    account: str
    start: date
    end: date


class Outcome(str, Enum):
    MATCHED = "matched"
    MISSED = "missed"
    NOT_ELIGIBLE = "not_eligible"
    BEFORE_CONFIRMATION = "before_confirmation"


class Status(str, Enum):
    DECLARED = "declared"
    VERIFIED = "verified"
    CONFLICT = "conflict"


@dataclass(frozen=True, slots=True)
class PaydayEvidence:
    pay_month: Month
    expected_payday: date
    version: int
    outcome: Outcome
    credit: Credit | None = None


@dataclass(frozen=True, slots=True)
class SalaryCheck:
    current: Declaration | None  # the version that applies to the pay month of today; None if every one starts later
    status: Status
    matched: int  # matches of the current version
    missed: int  # paydays of the current version counted as missed
    evidence: tuple[PaydayEvidence, ...]  # every pay month from the chain's first effective_from to today's

    def matched_amounts(self, version: int) -> tuple[int, ...]:
        """The matched credits of one version, in pay-month order: E in ADR-049 §6."""
        return tuple(e.credit.amount for e in self.evidence if e.version == version and e.credit is not None)


def eligible_inputs(
    user_id: str, statements: Sequence[StoredStatement], transactions: Sequence[PostedTransaction]
) -> tuple[tuple[Credit, ...], tuple[AccountSpan, ...]]:
    """The credits and the coverage a salary check may use, from what the user imported."""
    usable = {
        s.statement_id: s for s in statements
        if s.user_id == user_id and s.verified and not s.statement.provisional
        and s.statement.currency == CURRENCY and s.statement.account_type in CYCLE_ACCOUNTS
    }
    spans = tuple(sorted(
        {AccountSpan(f"{s.statement.bank}:{s.statement.account_ref}", s.statement.period_start, s.statement.period_end) for s in usable.values()},
        key=lambda a: (a.account, a.start, a.end),
    ))
    credits = {
        Credit(p.statement_id, p.transaction.txn_id, p.transaction.amount, p.transaction.date)
        for p in transactions
        if p.user_id == user_id and p.statement_id in usable and p.currency == CURRENCY
        and p.transaction.kind is TransactionKind.INCOME and p.transaction.amount > 0 and p.transaction.category not in OWN_MONEY
    }
    return tuple(sorted(credits, key=lambda c: (c.posted_on, c.txn_id, c.statement_id))), spans


def business_window(day: date, business_days: int) -> tuple[date, date]:
    """`day` ± that many weekdays, inclusive."""
    start = end = day
    for _ in range(business_days):
        start -= timedelta(days=1)
        while start.weekday() >= 5:
            start -= timedelta(days=1)
        end += timedelta(days=1)
        while end.weekday() >= 5:
            end += timedelta(days=1)
    return start, end


def window_eligible(start: date, end: date, spans: Sequence[AccountSpan], today: date) -> bool:
    if end >= today:
        return False  # not ended: a credit may still arrive
    by_account: dict[str, list[AccountSpan]] = defaultdict(list)
    for span in spans:
        by_account[span.account].append(span)
    return bool(by_account) and all(_covers(own, start, end) for own in by_account.values())


def _covers(spans: Sequence[AccountSpan], start: date, end: date) -> bool:
    reached = start - timedelta(days=1)
    for span in sorted(spans, key=lambda s: s.start):
        if span.start > reached + timedelta(days=1):
            break
        reached = max(reached, span.end)
        if reached >= end:
            return True
    return reached >= end


def check_salary(
    declarations: Sequence[Declaration],
    credits: Sequence[Credit],
    spans: Sequence[AccountSpan],
    today: date,
    rules: SalaryRules = PROPOSED_RULES,
) -> SalaryCheck:
    versions = chain(declarations)
    if not versions:
        raise ValueError("a salary check needs at least one declaration")
    this_month = Month.of(today)
    current = applicable(versions, this_month)
    cut = max(d.confirmed_at.date() for d in versions)  # the latest confirmation in the chain
    ordered = sorted(set(credits), key=lambda c: (c.posted_on, c.txn_id, c.statement_id))

    evidence: list[PaydayEvidence] = []
    used: set[str] = set()
    month = min(d.effective_from for d in versions)
    while month <= this_month:
        version = applicable(versions, month)
        assert version is not None  # every month from the first effective_from has one
        expected = payday(month)
        start, end = business_window(expected, rules.window_business_days)
        if not window_eligible(start, end, spans, today):
            evidence.append(PaydayEvidence(month, expected, version.version, Outcome.NOT_ELIGIBLE))
        else:
            declared = version.value.amount
            fitting = [
                c for c in ordered
                if start <= c.posted_on <= end and c.txn_id not in used and abs(c.amount - declared) <= rules.tolerance * declared
            ]
            if fitting:
                match = min(fitting, key=lambda c: (abs(c.amount - declared), c.posted_on, c.txn_id, c.statement_id))
                used.add(match.txn_id)
                evidence.append(PaydayEvidence(month, expected, version.version, Outcome.MATCHED, match))
            elif expected < cut:
                evidence.append(PaydayEvidence(month, expected, version.version, Outcome.BEFORE_CONFIRMATION))
            else:
                evidence.append(PaydayEvidence(month, expected, version.version, Outcome.MISSED))
        month = month.plus(1)

    run = longest = 0
    for item in evidence:
        run = run + 1 if item.outcome is Outcome.MISSED else 0
        longest = max(longest, run)
    own = [e for e in evidence if current is not None and e.version == current.version]
    matched = sum(1 for e in own if e.outcome is Outcome.MATCHED)
    missed = sum(1 for e in own if e.outcome is Outcome.MISSED)
    if longest >= rules.conflict_cycles:
        status = Status.CONFLICT
    elif matched:
        status = Status.VERIFIED
    else:
        status = Status.DECLARED
    return SalaryCheck(current, status, matched, missed, tuple(evidence))
