"""Spending check-in: logged spending against what the forecast already counts on (ADR-039).

The conservative forecast assumes the P80 of every spending category in each pay cycle. The check-in looks at the
cycle the user is in today (payday to the eve of the next payday) and compares the spending logged in it (receipts
the statements have not recorded yet, and statement charges) with that assumption:

    left     = assumed (P80 of the cycle's month, seasonal factor applied) - logged
    per_day  = left // days left in the cycle (today included), 0 once nothing is left
    overspend = logged beyond the assumption. In a cycle the forecast projects it lowers every later trough by the
               same amount, so it comes straight out of the protected surplus: surplus_after = protected surplus -
               overspend. In a cycle before the forecast's first one (a model built later than today) the forecast
               does not depend on it, so surplus_after stays the protected surplus and only a warning says so.

Everything is an integer in minor units; `per_day` rounds down so that spending it every day stays inside the
assumption. A category figure is the category's P80 with the same seasonal factor, rounded once.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from ..shared.envelope import Caveat, Fact
from ..shared.month import Month
from ..shared.numbers import round_half_up
from .model import FinancialModel
from .paycycle import cycle_end, cycle_of, cycle_start


@dataclass(frozen=True, slots=True)
class LoggedSpend:
    on: date
    amount: int  # positive magnitude, minor units
    category: str
    source: str  # receipt | statement
    ref: str  # receipt id or transaction id


@dataclass(frozen=True, slots=True)
class CategoryCheck:
    category: str
    assumed: int  # P80 for the cycle, seasonal factor applied
    logged: int


@dataclass(frozen=True, slots=True)
class SpendingCheck:
    cycle: Month
    window_start: date  # the cycle's payday
    window_end: date  # the eve of the next payday
    projected: bool  # the forecast projects this cycle, so an overspend lowers the protected surplus
    today: date
    days_left: int  # from today (inside the window) to the window's end, both included
    assumed: int  # conservative variable spending for the cycle (P80)
    logged: int
    logged_items: int
    left: int  # assumed - logged; negative once spending passed the assumption
    per_day: int
    overspend: int
    protected_surplus: int
    surplus_after: int  # protected surplus - overspend; negative means a conservative month breaches the floor
    categories: tuple[CategoryCheck, ...]  # the categories with logged spending


def spending_check(model: FinancialModel, logged: Sequence[LoggedSpend], today: date, protected_surplus: int) -> SpendingCheck:
    cycle = cycle_of(today)
    start, end = cycle_start(cycle), cycle_end(cycle)
    days_left = (end - today).days + 1
    projected = cycle >= model.first_cycle
    inside = [item for item in logged if start <= item.on <= end]
    assumed = model.spend.total(cycle, "p80")
    spent = sum(item.amount for item in inside)
    left = assumed - spent
    overspend = max(0, -left)
    factor = model.spend.factor(cycle)
    by_category: dict[str, int] = {}
    for item in inside:
        by_category[item.category] = by_category.get(item.category, 0) + item.amount
    assumed_by_category = {c.category: round_half_up(c.p80 * factor) for c in model.spend.categories}
    categories = tuple(
        CategoryCheck(name, assumed_by_category.get(name, 0), amount) for name, amount in sorted(by_category.items())
    )
    return SpendingCheck(
        cycle=cycle,
        window_start=start,
        window_end=end,
        projected=projected,
        today=today,
        days_left=days_left,
        assumed=assumed,
        logged=spent,
        logged_items=len(inside),
        left=left,
        per_day=left // days_left if left > 0 else 0,
        overspend=overspend,
        protected_surplus=protected_surplus,
        surplus_after=protected_surplus - overspend if projected else protected_surplus,
        categories=categories,
    )


def spending_caveats(check: SpendingCheck) -> tuple[Caveat, ...]:
    """Only what logged spending causes. A forecast already below the floor without it is the surplus tool's to say."""
    if check.overspend == 0:
        return ()
    if not check.projected:
        return (
            Caveat(
                "SPENDING_ABOVE_FORECAST",
                "Spending this cycle is past what the conservative forecast counts on for a pay cycle.",
                ("counts on", "pronóstico", "cuenta el pronóstico"),
            ),
        )
    if check.surplus_after < 0:
        return (
            Caveat(
                "SPENDING_BREACHES_FLOOR",
                "Spending this cycle is past what the forecast counts on and past your protected surplus: "
                "a conservative month would now drop below your minimum balance.",
                ("below your minimum", "bajo tu mínimo", "bajo el mínimo", "bajo tu saldo mínimo", "bajo tu piso", "bajo el piso"),
            ),
        )
    if check.overspend > 0:
        return (
            Caveat(
                "SPENDING_ABOVE_FORECAST",
                "Spending this cycle is past what the conservative forecast counts on; the extra comes out of your protected surplus.",
                ("protected surplus", "excedente protegido"),
            ),
        )
    return ()


def spending_facts(check: SpendingCheck, currency: str) -> tuple[Fact, ...]:
    facts = [
        Fact("spending.cycle", str(check.cycle), "month", "first projected pay cycle"),
        Fact("spending.window_start", check.window_start.isoformat(), "date", "the cycle's payday"),
        Fact("spending.window_end", check.window_end.isoformat(), "date", "eve of the next payday"),
        Fact("spending.days_left", check.days_left, "days", "today to the eve of payday, both included"),
        Fact("spending.assumed", check.assumed, currency, "conservative (P80) variable spending the forecast counts on"),
        Fact("spending.logged", check.logged, currency, "receipts not yet on a statement + statement charges, in this cycle"),
        Fact("spending.logged_items", check.logged_items, "count", "receipts and charges counted"),
        Fact("spending.left", check.left, currency, "assumed - logged"),
        Fact("spending.per_day", check.per_day, currency, "left // days left, rounded down"),
        Fact("spending.overspend", check.overspend, currency, "logged beyond the assumption"),
        Fact("protected_surplus", check.protected_surplus, currency, "min conservative headroom over the horizon"),
        Fact("spending.surplus_after", check.surplus_after, currency, "protected surplus - overspend"),
    ]
    for c in check.categories:
        facts.append(Fact(f"spending.{c.category}.assumed", c.assumed, currency, "category P80 for the cycle"))
        facts.append(Fact(f"spending.{c.category}.logged", c.logged, currency, "logged in the category this cycle"))
    return tuple(facts)
