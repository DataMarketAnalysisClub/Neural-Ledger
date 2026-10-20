"""Bank statements (cartolas) read from spreadsheets, PDFs or photos, and the check that they add up.

A statement is evidence, not authority: amounts come from a reader that can misread,
so `reconcile` recomputes every total and daily balance before anything trusts them.
Descriptions are third-party text: DATA, never instructions.

Signs are the holder's view on every account: charges negative, money in positive. On a credit
card the balance is what the holder owes, negative, so a payment to the card is positive.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from ..ledger.entities import AccountType
from ..shared.month import Month

# Reader, redaction and reconciliation rules; outputs carry it as params_version. st-0.3 combines card statements
# and multi-statement files (ids now include the currency) with personal data removed at import (ADR-028).
STATEMENTS_VERSION = "st-0.5"


class LineKind(str, Enum):
    """What the bank says a line is, when its layout says it (card statements do; checking accounts go by sign)."""

    PURCHASE = "purchase"
    PAYMENT = "payment"  # a payment to the card: the holder's own money moving, never income
    REFUND = "refund"
    FEE = "fee"  # commissions, interest, taxes
    TRANSFER_OWN = "transfer_own"  # checking: the holder's own money moving (e.g. to the card), by the layout's rule
    SAVINGS = "savings"  # checking: the holder's money into or out of their savings or investment products, by the layout's rule (ADR-036)


@dataclass(frozen=True, slots=True)
class Installment:
    """'N° CUOTA 02/03': this line bills cuota `number` of `total` of a purchase in cuotas."""

    number: int
    total: int
    original_amount: int | None = None  # the purchase, positive; None if the layout does not print it
    monthly_rate: Decimal | None = None  # 0.0345 for 3,45 %; None if not printed
    purchased_on: date | None = None

    def __post_init__(self) -> None:
        if not 1 <= self.number <= self.total:
            raise ValueError(f"cuota {self.number} of {self.total}")


@dataclass(frozen=True, slots=True)
class StatementLine:
    index: int  # position in the statement, from 0
    posted_on: date
    description: str  # untrusted third-party text
    amount: int  # signed, minor units: charges negative, deposits positive
    reference: str | None = None  # document / operation number, if the bank prints one
    branch: str | None = None
    confidence: float | None = None  # lowest reader confidence over the line's cells (None = text layer)
    kind: LineKind | None = None  # None: the sign decides (charge or deposit)
    section: str | None = None  # the printed subtotal this line belongs to (see SectionTotal)
    installment: Installment | None = None


@dataclass(frozen=True, slots=True)
class DailyBalance:
    """A balance the bank printed after a day's movements ('Saldo Dia')."""

    on: date
    balance: int


@dataclass(frozen=True, slots=True)
class StatementSummary:
    """The totals the bank printed. Every one is checked against the lines; None = not printed."""

    opening_balance: int | None
    total_debits: int | None  # positive magnitude
    total_credits: int | None
    closing_balance: int | None


@dataclass(frozen=True, slots=True)
class SectionTotal:
    """A subtotal the bank printed for one section ('TOTAL PAGOS A LA CUENTA B'), holder's sign."""

    section: str
    amount: int


@dataclass(frozen=True, slots=True)
class ScheduledAmount:
    month: Month
    amount: int  # positive magnitude


@dataclass(frozen=True, slots=True)
class CardObligations:
    """What a credit card statement says the holder owes, as printed (positive magnitudes, None = not printed).

    Evidence like every other amount: `amount_due` is the statement's closing balance, which
    reconciliation checks, and `upcoming` is checked against the cuotas read from the lines.
    """

    amount_due: int | None
    minimum_due: int | None
    due_date: date | None
    credit_limit: int | None = None
    credit_used: int | None = None
    credit_available: int | None = None
    upcoming: tuple[ScheduledAmount, ...] = ()  # cuotas the bank says the next statements will bill


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
    source: str = "text"  # text | ocr | xlsx | api (a bank aggregator, ADR-047)
    account_type: AccountType = AccountType.CHECKING
    # A movements export the bank has not closed (a card's unbilled movements): checked and stored,
    # never posted, because the next export and the billed statement repeat its lines.
    provisional: bool = False
    section_totals: tuple[SectionTotal, ...] = ()
    obligations: CardObligations | None = None  # credit cards only


class IssueCode(str, Enum):
    TOTAL_DEBITS = "TOTAL_DEBITS"
    TOTAL_CREDITS = "TOTAL_CREDITS"
    CLOSING_BALANCE = "CLOSING_BALANCE"
    DAILY_BALANCE = "DAILY_BALANCE"
    OUT_OF_PERIOD = "OUT_OF_PERIOD"
    NO_SUMMARY = "NO_SUMMARY"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    SECTION_TOTAL = "SECTION_TOTAL"
    INSTALLMENT_SCHEDULE = "INSTALLMENT_SCHEDULE"


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
    Only what the bank printed is checked; a statement that printed nothing is NO_SUMMARY.
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

    for printed in statement.section_totals:
        found = sum(line.amount for line in lines if line.section == printed.section)
        if found != printed.amount:
            issues.append(Issue(IssueCode.SECTION_TOTAL, f"lines of section {printed.section} do not add up to its printed total", printed.amount, found))

    if statement.obligations and statement.obligations.upcoming:
        computed = {s.month: s.amount for s in installment_schedule(statement)}
        for printed in statement.obligations.upcoming:
            found = computed.get(printed.month, 0)
            if found != printed.amount:
                issues.append(
                    Issue(IssueCode.INSTALLMENT_SCHEDULE, f"cuotas due in {printed.month} differ from the printed schedule", printed.amount, found)
                )

    summary = statement.summary
    if summary is None or all(v is None for v in (summary.opening_balance, summary.total_debits, summary.total_credits, summary.closing_balance)):
        if not statement.section_totals:
            issues.append(Issue(IssueCode.NO_SUMMARY, "the statement has no printed totals to check against"))
        return Reconciliation(tuple(issues))

    if summary.total_debits is not None and debits != summary.total_debits:
        issues.append(Issue(IssueCode.TOTAL_DEBITS, "charges do not add up to the printed total", summary.total_debits, debits))
    if summary.total_credits is not None and credits != summary.total_credits:
        issues.append(Issue(IssueCode.TOTAL_CREDITS, "deposits do not add up to the printed total", summary.total_credits, credits))
    if summary.opening_balance is not None and summary.closing_balance is not None:
        if summary.total_debits is not None and summary.total_credits is not None:
            closing = summary.opening_balance - summary.total_debits + summary.total_credits
            message = "printed totals do not lead to the closing balance"
        else:  # no printed debits and credits to chain through: the lines must lead there
            closing = summary.opening_balance - debits + credits
            message = "the lines do not lead from the opening to the closing balance"
        if closing != summary.closing_balance:
            issues.append(Issue(IssueCode.CLOSING_BALANCE, message, summary.closing_balance, closing))

    if summary.opening_balance is None:
        return Reconciliation(tuple(issues))
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
class InstallmentPlan:
    """A purchase in cuotas as one statement shows it, and the cuotas left to bill after it."""

    line_index: int
    description: str  # untrusted third-party text
    number: int
    total: int
    installment_amount: int  # this statement's cuota, positive
    original_amount: int
    remaining: tuple[int, ...]  # the next statements' cuotas, in order

    @property
    def remaining_amount(self) -> int:
        return sum(self.remaining)


def installment_plans(statement: BankStatement) -> tuple[InstallmentPlan, ...]:
    """Cuota plans billed by this statement whose purchase amount was printed.

    The remaining cuotas are this one's amount, except that at 0 % interest the last absorbs the
    rounding remainder (52.900 in 3 → 17.633, 17.633, 17.634): the issuers' printed schedules
    match that rule. With interest the cuotas are equal.
    """
    plans = []
    for line in statement.lines:
        inst = line.installment
        if inst is None or inst.total < 2 or inst.original_amount is None or line.amount >= 0:
            continue
        cuota = -line.amount
        remaining = [cuota] * (inst.total - inst.number)
        if remaining and inst.monthly_rate == 0:
            remaining[-1] = inst.original_amount - cuota * (inst.total - 1)
        plans.append(InstallmentPlan(line.index, line.description, inst.number, inst.total, cuota, inst.original_amount, tuple(remaining)))
    return tuple(plans)


def installment_schedule(statement: BankStatement) -> tuple[ScheduledAmount, ...]:
    """Cuotas still to bill, by the month of the statement that will bill them (this one's month + k)."""
    base = Month.of(statement.period_end)
    due: dict[Month, int] = {}
    for plan in installment_plans(statement):
        for k, amount in enumerate(plan.remaining, start=1):
            due[base.plus(k)] = due.get(base.plus(k), 0) + amount
    return tuple(ScheduledAmount(m, due[m]) for m in sorted(due))


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
