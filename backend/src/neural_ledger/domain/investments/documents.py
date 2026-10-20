"""Investment statements the user downloads from the provider and drops in the app (ADR-044, statement import).

Fintual's "Investment Statement" lists the shares of every fund and series the user held on one day, with the value
per share and the balance in pesos, and the total. Its "Certificado de transacciones" lists every contribution
(aporte) and withdrawal (rescate) per goal, fund and series, with the shares the goal held at the end of that day.
A reader adapter extracts the rows; this module decides whether they add up, and only a document that does is used:

    holdings   every balance is its shares times the value per share (to the peso) and the balances add up to the
               printed total
    movements  for each goal, fund and series, every day's shares are the previous day's plus that day's
               contributions less its withdrawals; each row's pesos are its shares times the value per share; the
               moves between the user's own goals add up to zero
    together   when the movements end on or before the statement's day and the shares per fund and series match,
               each goal's value is its part of the printed balance; when the certificate also starts from zero
               shares, the gain is the value less the net contributions

The holder's name and RUT are never read into these types. Goal names are the user's own labels: untrusted text.
Pesos are integers; shares and values per share stay exact decimals, and ratios exact until the final rounding.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from fractions import Fraction

from ..shared.envelope import Caveat, Fact
from ..shared.hashing import content_id
from ..shared.numbers import round_half_up
from .model import MAX_AMOUNT, PROVIDERS

MAX_POSITIONS = 60  # fund and series rows on one statement
MAX_MOVEMENTS = 5000  # rows on one certificate
MAX_DOCUMENTS = 24  # verified documents kept per user; the oldest go first
MAX_GOAL_NAME = 120
MAX_SHARES = Decimal(10) ** 10
PESO_TOLERANCE = 1  # printed pesos are shares times the value per share, rounded or truncated
OLD_AFTER = timedelta(days=31)  # a statement older than this is described as old
EARLIEST = date(2000, 1, 1)
CURRENCY = "CLP"

_FUND_NAME = re.compile(r"[A-Za-z][A-Za-z0-9 .\-]{0,59}")
_SERIES = re.compile(r"[A-Z0-9]{1,6}")


class InvestmentDocumentKind(str, Enum):
    HOLDINGS = "holdings"  # every fund and series on one day (Fintual's Investment Statement)
    MOVEMENTS = "movements"  # every contribution and withdrawal (Fintual's Certificado de transacciones)


@dataclass(frozen=True, slots=True)
class FundPosition:
    fund: str  # the provider's fund name, e.g. "Risky Norris"
    series: str  # A, APV, Z...
    shares: Decimal
    share_value: Decimal  # pesos per share on the statement's day
    balance: int  # pesos, as printed


@dataclass(frozen=True, slots=True)
class FundMovement:
    day: date
    goal: str  # the user's label for the goal at the provider: untrusted text
    fund: str
    series: str
    shares_in: Decimal
    shares_out: Decimal
    share_value: Decimal
    shares_after: Decimal  # the goal's shares of this fund and series at the end of the day
    pesos_in: int
    pesos_out: int
    internal: bool  # a move between the user's own goals or funds, not money from or to the bank
    pesos_after: int


@dataclass(frozen=True, slots=True)
class ReadInvestmentDocument:
    """What a reader extracted from one document, before any check. Nothing about the holder is read."""

    provider: str
    kind: InvestmentDocumentKind
    as_of: date | None = None  # holdings: the day of the balances (the certificate's is its last movement's day)
    positions: tuple[FundPosition, ...] = ()
    total: int | None = None
    movements: tuple[FundMovement, ...] = ()


class DocumentIssue(str, Enum):
    NO_ROWS = "NO_ROWS"
    DATE_MISSING = "DATE_MISSING"
    DATE_OUT_OF_RANGE = "DATE_OUT_OF_RANGE"
    OUT_OF_RANGE = "OUT_OF_RANGE"
    TOTAL_MISMATCH = "TOTAL_MISMATCH"
    BALANCE_MISMATCH = "BALANCE_MISMATCH"
    SHARES_DO_NOT_CHAIN = "SHARES_DO_NOT_CHAIN"
    PESOS_MISMATCH = "PESOS_MISMATCH"
    INTERNAL_UNBALANCED = "INTERNAL_UNBALANCED"


ISSUE_MESSAGES = {
    DocumentIssue.NO_ROWS: "no fund rows could be read",
    DocumentIssue.DATE_MISSING: "the statement's date could not be read",
    DocumentIssue.DATE_OUT_OF_RANGE: "a date is in the future or before 2000",
    DocumentIssue.OUT_OF_RANGE: "a row repeats, or an amount, a number of shares or a name is outside what a statement holds",
    DocumentIssue.TOTAL_MISMATCH: "the fund balances do not add up to the printed total",
    DocumentIssue.BALANCE_MISMATCH: "a balance is not its shares times the value per share",
    DocumentIssue.SHARES_DO_NOT_CHAIN: "a day's shares are not the previous day's plus contributions less withdrawals",
    DocumentIssue.PESOS_MISMATCH: "a movement's pesos are not its shares times the value per share",
    DocumentIssue.INTERNAL_UNBALANCED: "the moves between the user's own goals do not add up to zero",
}


@dataclass(frozen=True, slots=True)
class StoredInvestmentDocument:
    """A verified document as stored: goal names already sanitized and redacted. Unverified documents are not kept."""

    document_id: str
    user_id: str
    provider: str
    kind: InvestmentDocumentKind
    imported_at: datetime
    as_of: date  # the statement's day, or the certificate's last movement
    positions: tuple[FundPosition, ...] = ()
    total: int | None = None
    movements: tuple[FundMovement, ...] = ()

    @property
    def rows(self) -> int:
        return len(self.positions) + len(self.movements)


def document_id(user_id: str, read: ReadInvestmentDocument) -> str:
    """The same document, read again, gets the same id: importing it twice stores it once."""
    return content_id("invdoc", user_id, read.provider, read.kind, read.as_of, read.total, read.positions, read.movements)


def document_day(read: ReadInvestmentDocument) -> date | None:
    if read.kind is InvestmentDocumentKind.HOLDINGS:
        return read.as_of
    return max((m.day for m in read.movements), default=None)


# ---- checks -------------------------------------------------------------------------------------


def check_document(read: ReadInvestmentDocument, today: date) -> tuple[DocumentIssue, ...]:
    """Every reason the document cannot be trusted, in a fixed order; empty when it adds up."""
    if read.provider not in PROVIDERS:
        return (DocumentIssue.OUT_OF_RANGE,)
    if read.kind is InvestmentDocumentKind.HOLDINGS:
        return _check_holdings(read, today)
    return _check_movements(read.movements, today)


def _check_holdings(read: ReadInvestmentDocument, today: date) -> tuple[DocumentIssue, ...]:
    if not read.positions or read.total is None:
        return (DocumentIssue.NO_ROWS,)
    positions = read.positions
    keys = {(p.fund, p.series) for p in positions}
    if len(positions) > MAX_POSITIONS or len(keys) != len(positions) or not 0 <= read.total <= MAX_AMOUNT:
        return (DocumentIssue.OUT_OF_RANGE,)
    if not all(_fund_ok(p.fund, p.series) and _shares_ok(p.shares) and _value_ok(p.share_value) and 0 <= p.balance <= MAX_AMOUNT for p in positions):
        return (DocumentIssue.OUT_OF_RANGE,)
    issues = []
    if read.as_of is None:
        issues.append(DocumentIssue.DATE_MISSING)
    elif not EARLIEST <= read.as_of <= today:
        issues.append(DocumentIssue.DATE_OUT_OF_RANGE)
    if sum(p.balance for p in positions) != read.total:
        issues.append(DocumentIssue.TOTAL_MISMATCH)
    if any(not _pesos_match(p.shares, p.share_value, p.balance) for p in positions):
        issues.append(DocumentIssue.BALANCE_MISMATCH)
    return tuple(issues)


def _check_movements(movements: Sequence[FundMovement], today: date) -> tuple[DocumentIssue, ...]:
    if not movements:
        return (DocumentIssue.NO_ROWS,)
    if len(movements) > MAX_MOVEMENTS or not all(_movement_ok(m) for m in movements):
        return (DocumentIssue.OUT_OF_RANGE,)
    issues = []
    if any(not EARLIEST <= m.day <= today for m in movements):
        issues.append(DocumentIssue.DATE_OUT_OF_RANGE)
    if any(not _movement_adds_up(m) for m in movements):
        issues.append(DocumentIssue.PESOS_MISMATCH)
    if _chains(movements) is None:
        issues.append(DocumentIssue.SHARES_DO_NOT_CHAIN)
    if sum(m.pesos_in for m in movements if m.internal) != sum(m.pesos_out for m in movements if m.internal):
        issues.append(DocumentIssue.INTERNAL_UNBALANCED)
    return tuple(issues)


def _fund_ok(fund: str, series: str) -> bool:
    return isinstance(fund, str) and isinstance(series, str) and bool(_FUND_NAME.fullmatch(fund)) and bool(_SERIES.fullmatch(series))


def _shares_ok(shares: Decimal) -> bool:
    return isinstance(shares, Decimal) and shares.is_finite() and 0 <= shares <= MAX_SHARES


def _value_ok(value: Decimal) -> bool:
    return isinstance(value, Decimal) and value.is_finite() and 0 <= value <= MAX_AMOUNT


def _movement_ok(m: FundMovement) -> bool:
    return (
        _fund_ok(m.fund, m.series)
        and isinstance(m.goal, str)
        and 0 < len(m.goal.strip()) <= MAX_GOAL_NAME
        and all(_shares_ok(s) for s in (m.shares_in, m.shares_out, m.shares_after))
        and _value_ok(m.share_value)
        and all(isinstance(p, int) and not isinstance(p, bool) and 0 <= p <= MAX_AMOUNT for p in (m.pesos_in, m.pesos_out, m.pesos_after))
    )


def _pesos_match(shares: Decimal, value: Decimal, pesos: int) -> bool:
    return abs(shares * value - pesos) <= PESO_TOLERANCE


def _movement_adds_up(m: FundMovement) -> bool:
    one_way = (m.shares_in > 0) != (m.shares_out > 0)  # a row is a contribution or a withdrawal, never both
    return (
        one_way
        and _pesos_match(m.shares_in, m.share_value, m.pesos_in)
        and _pesos_match(m.shares_out, m.share_value, m.pesos_out)
        and _pesos_match(m.shares_after, m.share_value, m.pesos_after)
    )


Chain = tuple[str, str, str]  # goal, fund, series


def _chains(movements: Sequence[FundMovement]) -> dict[Chain, tuple[Decimal, Decimal]] | None:
    """Opening and closing shares per goal, fund and series; None when a day does not follow from the one before.

    Rows of one day share the end-of-day shares, so a day is checked as a whole. The opening is what the first day
    implies (its shares less its net movement): zero when the certificate covers the whole history."""
    days: dict[Chain, dict[date, list[FundMovement]]] = defaultdict(lambda: defaultdict(list))
    for m in movements:
        days[(m.goal, m.fund, m.series)][m.day].append(m)
    chains: dict[Chain, tuple[Decimal, Decimal]] = {}
    for key, by_day in days.items():
        opening: Decimal | None = None
        closing = Decimal(0)
        for day in sorted(by_day):
            rows = by_day[day]
            after = {m.shares_after for m in rows}
            if len(after) != 1:
                return None
            end = after.pop()
            net = sum((m.shares_in - m.shares_out for m in rows), Decimal(0))
            if opening is None:
                opening = end - net
                if opening < 0:
                    return None
            elif closing + net != end:
                return None
            closing = end
        chains[key] = (opening if opening is not None else Decimal(0), closing)
    return chains


# ---- what the documents say together --------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GoalFlows:
    goal: str
    contributed: int  # from the bank
    withdrawn: int  # to the bank
    moved_in: int  # from the user's other goals or funds
    moved_out: int

    @property
    def net(self) -> int:
        return self.contributed - self.withdrawn + self.moved_in - self.moved_out


@dataclass(frozen=True, slots=True)
class MovementHistory:
    first_day: date
    last_day: date
    contributions: int  # rows of money in from the bank
    withdrawals: int  # rows of money out to the bank
    contributed: int
    withdrawn: int
    months: int  # calendar months from the first movement to the last, both included
    active_months: int  # months with at least one contribution from the bank
    last_contribution: date | None
    complete: bool  # every goal, fund and series starts from zero shares: the whole history is there
    goals: tuple[GoalFlows, ...]
    closing: tuple[tuple[str, str, str, Decimal], ...]  # shares per goal, fund and series after the last movement

    @property
    def net_contributed(self) -> int:
        return self.contributed - self.withdrawn

    @property
    def monthly_average(self) -> int:
        """Contributions from the bank divided by the months the certificate spans, rounded half up once."""
        return round_half_up(Fraction(self.contributed, self.months))


def movement_history(movements: Sequence[FundMovement]) -> MovementHistory:
    """The contribution habits a verified certificate shows. Raises ValueError on one that does not chain."""
    chains = _chains(movements)
    if chains is None or not movements:
        raise ValueError("the movements do not chain")
    days = [m.day for m in movements]
    first, last = min(days), max(days)
    bank_in = [m for m in movements if not m.internal and m.pesos_in > 0]
    bank_out = [m for m in movements if not m.internal and m.pesos_out > 0]
    flows: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0, 0])
    for m in movements:
        f = flows[m.goal]
        if m.internal:
            f[2] += m.pesos_in
            f[3] += m.pesos_out
        else:
            f[0] += m.pesos_in
            f[1] += m.pesos_out
    return MovementHistory(
        first_day=first,
        last_day=last,
        contributions=len(bank_in),
        withdrawals=len(bank_out),
        contributed=sum(m.pesos_in for m in bank_in),
        withdrawn=sum(m.pesos_out for m in bank_out),
        months=(last.year - first.year) * 12 + last.month - first.month + 1,
        active_months=len({(m.day.year, m.day.month) for m in bank_in}),
        last_contribution=max((m.day for m in bank_in), default=None),
        complete=all(opening == 0 for opening, _ in chains.values()),
        goals=tuple(GoalFlows(goal, *values) for goal, values in sorted(flows.items())),
        closing=tuple((goal, fund, series, end) for (goal, fund, series), (_, end) in sorted(chains.items())),
    )


@dataclass(frozen=True, slots=True)
class GoalHolding:
    goal: str
    value: int | None  # its part of the statement's balances, when both documents agree
    net_contributed: int  # contributions less withdrawals, moves between the user's goals included
    gain: int | None  # value less net contributions, when the certificate holds the whole history


@dataclass(frozen=True, slots=True)
class Portfolio:
    """What the newest verified statement and certificate say together."""

    provider: str
    as_of: date
    holdings: StoredInvestmentDocument | None
    movements: StoredInvestmentDocument | None
    history: MovementHistory | None
    goals: tuple[GoalHolding, ...]
    agree: bool | None  # both documents describe the same shares; None unless both are there

    @property
    def positions(self) -> tuple[FundPosition, ...]:
        """The funds held: rows of zero shares and zero balance are left out."""
        return tuple(p for p in self.holdings.positions if p.shares or p.balance) if self.holdings else ()

    @property
    def total_value(self) -> int | None:
        return self.holdings.total if self.holdings else None

    @property
    def total_deposited(self) -> int | None:
        return self.history.net_contributed if self.history else None

    @property
    def total_gain(self) -> int | None:
        if self.total_value is None or self.history is None or not self.history.complete or not self.agree:
            return None
        return self.total_value - self.history.net_contributed

    @property
    def gain_pct(self) -> Decimal | None:
        gain, deposited = self.total_gain, self.total_deposited
        if gain is None or deposited is None or deposited <= 0:
            return None
        return (Decimal(gain) * 100 / Decimal(deposited)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def portfolio(provider: str, holdings: StoredInvestmentDocument | None, movements: StoredInvestmentDocument | None) -> Portfolio:
    if holdings is None and movements is None:
        raise ValueError("a portfolio needs a document")
    history = movement_history(movements.movements) if movements else None
    agree = _agree(holdings, history) if holdings and history else None
    goals: tuple[GoalHolding, ...] = ()
    if history is not None:
        values = _goal_values(holdings, history) if holdings and agree else {}
        goals = tuple(
            GoalHolding(
                f.goal,
                values.get(f.goal),
                f.net,
                values[f.goal] - f.net if f.goal in values and history.complete else None,
            )
            for f in history.goals
        )
    as_of = holdings.as_of if holdings else history.last_day  # type: ignore[union-attr]
    return Portfolio(provider, as_of, holdings, movements, history, goals, agree)


def _agree(holdings: StoredInvestmentDocument, history: MovementHistory) -> bool:
    if history.last_day > holdings.as_of:
        return False
    held: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    for _, fund, series, shares in history.closing:
        held[(fund, series)] += shares
    printed = {(p.fund, p.series): p.shares for p in holdings.positions}
    return all(held.get(key, Decimal(0)) == printed.get(key, Decimal(0)) for key in held.keys() | printed.keys())


def _goal_values(holdings: StoredInvestmentDocument, history: MovementHistory) -> dict[str, int]:
    """Each fund's printed balance split among the goals by their shares (largest remainder, ties by goal name), so
    the goals add up to the statement's total to the peso."""
    owners: dict[tuple[str, str], list[tuple[str, Decimal]]] = defaultdict(list)
    for goal, fund, series, shares in history.closing:
        if shares:
            owners[(fund, series)].append((goal, shares))
    values: dict[str, int] = {f.goal: 0 for f in history.goals}
    for p in holdings.positions:
        held = owners.get((p.fund, p.series), [])
        total_shares = sum((s for _, s in held), Decimal(0))
        if not held or not total_shares:
            continue
        exact = [(goal, Fraction(p.balance) * Fraction(shares) / Fraction(total_shares)) for goal, shares in held]
        parts = {goal: int(x) for goal, x in exact}
        left = p.balance - sum(parts.values())
        for goal, _ in sorted(exact, key=lambda gx: (-(gx[1] - int(gx[1])), gx[0]))[:left]:
            parts[goal] += 1
        for goal, part in parts.items():
            values[goal] += part
    return values


def fund_id(position: FundPosition) -> str:
    return re.sub(r"[^a-z0-9]+", "_", f"{position.fund} {position.series}".lower()).strip("_")


def goal_id(provider: str, goal: str) -> str:
    return content_id("goal", provider, goal)


# ---- what the agent may say ----------------------------------------------------------------------------


def portfolio_facts(p: Portfolio) -> tuple[Fact, ...]:
    """Every number the agent may say about the imported documents. Balances are printed ones; the rest is ours."""
    name = PROVIDERS[p.provider]
    facts: list[Fact] = []
    if p.holdings is not None:
        on = p.holdings.as_of.isoformat()
        facts.append(Fact("investments.total_value", p.holdings.total or 0, CURRENCY, f"total balance on {on} in the {name} statement the user imported"))
        facts.append(Fact("investments.funds", len(p.positions), "count", f"funds and series held on {on}"))
        for position in p.positions:
            facts.append(Fact(f"investments.fund.{fund_id(position)}.value", position.balance, CURRENCY, f"{position.fund} {position.series} balance on {on}"))
    h = p.history
    if h is not None:
        span = f"from {h.first_day.isoformat()} to {h.last_day.isoformat()}"
        facts += [
            Fact("investments.contributed", h.contributed, CURRENCY, f"contributions from the bank {span}"),
            Fact("investments.withdrawn", h.withdrawn, CURRENCY, f"withdrawals to the bank {span}"),
            Fact("investments.total_deposited", h.net_contributed, CURRENCY, "contributions less withdrawals"),
            Fact("investments.contributions", h.contributions, "count", f"contributions from the bank {span}"),
            Fact("investments.withdrawals", h.withdrawals, "count", f"withdrawals to the bank {span}"),
            Fact("investments.monthly_contribution", h.monthly_average, CURRENCY, f"contributions divided by the {h.months} months {span}"),
            Fact("investments.history_months", h.months, "count", f"calendar months {span}"),
            Fact("investments.contribution_months", h.active_months, "count", "months with at least one contribution"),
        ]
    if p.total_gain is not None:
        facts.append(Fact("investments.total_gain", p.total_gain, CURRENCY, "total balance less contributions less withdrawals"))
    if p.gain_pct is not None:
        facts.append(Fact("investments.gain_pct", float(p.gain_pct), "%", "total gain over contributions less withdrawals"))
    if p.goals:
        facts.append(Fact("investments.goals", len(p.goals), "count", "goals in the transactions certificate"))
    for goal in p.goals:
        gid = goal_id(p.provider, goal.goal)
        if goal.value is not None:
            facts.append(Fact(f"investments.goal.{gid}.value", goal.value, CURRENCY, "the goal's part of each fund balance, by its shares"))
        facts.append(Fact(f"investments.goal.{gid}.deposited", goal.net_contributed, CURRENCY, "goal contributions less withdrawals, moves included"))
        if goal.gain is not None:
            facts.append(Fact(f"investments.goal.{gid}.gain", goal.gain, CURRENCY, "goal value less its net contributions"))
    return tuple(facts)


def portfolio_caveats(p: Portfolio, today: date) -> tuple[Caveat, ...]:
    """What the agent must say with those numbers. They describe the past: never a forecast, never advice."""
    name = PROVIDERS[p.provider]
    caveats = [
        Caveat(
            "INVESTMENTS_FROM_STATEMENT",
            f"These figures come from the {name} documents you imported, as of {p.as_of.isoformat()}; values change "
            "every day, and past gains do not predict future ones.",
            (name,),
        )
    ]
    if today - p.as_of > OLD_AFTER:
        caveats.append(
            Caveat(
                "INVESTMENTS_STATEMENT_OLD",
                f"The newest document is from {p.as_of.isoformat()}, more than a month ago; import a newer one for current values.",
                ("statement", "cartola", "estado de cuenta", "certificado", "document"),
            )
        )
    if p.holdings is None:
        caveats.append(Caveat("INVESTMENTS_NO_BALANCE", "Without the investment statement, the current value and the gain are unknown."))
    if p.history is None:
        caveats.append(Caveat("INVESTMENTS_NO_HISTORY", "Without the transactions certificate, the contributions and the gain are unknown."))
    elif not p.history.complete:
        caveats.append(
            Caveat(
                "INVESTMENTS_PARTIAL_HISTORY",
                "The transactions certificate starts after the account opened, so the contributions are partial and the gain is not computed.",
                ("partial", "parcial", "incomplet"),
            )
        )
    if p.agree is False:
        caveats.append(
            Caveat(
                "INVESTMENTS_DOCUMENTS_DISAGREE",
                "The statement and the transactions certificate do not describe the same shares (they are from different days), "
                "so the value per goal and the gain are not computed; import both downloaded on the same day.",
            )
        )
    return tuple(caveats)
