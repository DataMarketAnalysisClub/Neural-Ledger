"""Forecast engine (Financial Core 4.4).

Liquidity is checked at each pay cycle's TROUGH: the balance just before salary arrives.
    B_m = B_(m-1) + I_m - K_m - V_m - R_m - P_m - S_m        H_m = B_m - Floor
A month breaches when H_m < 0. Typical: contracted/P50 income, P50 spend. Conservative:
contracted/P20 income, P80 spend (used for every decision). Stress: conservative + one shock.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..shared.envelope import Fact
from ..shared.month import Month, month_range
from .model import FinancialModel
from .params import FinanceParams


class Scenario(str, Enum):
    TYPICAL = "typical"
    CONSERVATIVE = "conservative"
    STRESS = "stress"


@dataclass(frozen=True, slots=True)
class Recurring:
    """A monthly amount leaving checking from `start` to `end` (inclusive; None = open-ended)."""

    amount: int
    start: Month
    end: Month | None = None

    def at(self, month: Month) -> int:
        if self.start <= month and (self.end is None or month <= self.end):
            return self.amount
        return 0


@dataclass(frozen=True, slots=True)
class CycleProjection:
    month: Month
    income: int
    commitments: int
    variable: int
    available: int  # income - commitments - variable
    plan: int
    purchase: int
    shock: int
    trough: int
    headroom: int


@dataclass(frozen=True, slots=True)
class Forecast:
    scenario: Scenario
    floor: int
    opening_trough: int
    cycles: tuple[CycleProjection, ...]

    @property
    def breaches(self) -> tuple[Month, ...]:
        return tuple(c.month for c in self.cycles if c.headroom < 0)

    @property
    def lowest(self) -> CycleProjection:
        return min(self.cycles, key=lambda c: (c.headroom, c.month))

    def cycle(self, month: Month) -> CycleProjection:
        for c in self.cycles:
            if c.month == month:
                return c
        raise KeyError(str(month))


def stress_shock(model: FinancialModel, params: FinanceParams) -> int:
    return max(params.stress_shock_min, model.largest_one_off_expense)


def project(
    model: FinancialModel,
    params: FinanceParams,
    scenario: Scenario,
    horizon: int,
    *,
    plan: Recurring | None = None,
    purchases: tuple[Recurring, ...] = (),
    shock: Recurring | None = None,
) -> Forecast:
    if horizon < 1:
        raise ValueError("horizon must be at least 1 month")
    if scenario is Scenario.STRESS and shock is None:
        shock = Recurring(stress_shock(model, params), model.first_cycle, model.first_cycle)
    quantile = "p50" if scenario is Scenario.TYPICAL else "p80"
    income = model.income.typical if scenario is Scenario.TYPICAL else model.income.conservative

    balance = model.balances.checking
    cycles: list[CycleProjection] = []
    for month in month_range(model.first_cycle, horizon):
        commitments = model.commitments_due(month)
        variable = model.spend.total(month, quantile)
        available = income - commitments - variable
        plan_out = plan.at(month) if plan else 0
        purchase_out = sum(p.at(month) for p in purchases)
        shock_out = shock.at(month) if shock else 0
        balance = balance + available - plan_out - purchase_out - shock_out
        cycles.append(
            CycleProjection(
                month=month,
                income=income,
                commitments=commitments,
                variable=variable,
                available=available,
                plan=plan_out,
                purchase=purchase_out,
                shock=shock_out,
                trough=balance,
                headroom=balance - params.liquidity_floor,
            )
        )
    return Forecast(scenario, params.liquidity_floor, model.balances.checking, tuple(cycles))


def forecast_facts(forecast: Forecast, currency: str) -> tuple[Fact, ...]:
    s = forecast.scenario.value
    facts: list[Fact] = [Fact("liquidity_floor", forecast.floor, currency, "parameter register")]
    for c in forecast.cycles:
        m = str(c.month)
        facts += [
            Fact(f"{m}.{s}.income", c.income, currency, "income model"),
            Fact(f"{m}.{s}.commitments", c.commitments, currency, "commitment schedule"),
            Fact(f"{m}.{s}.variable", c.variable, currency, f"spend model ({'P50' if s == 'typical' else 'P80'})"),
            Fact(f"{m}.{s}.available", c.available, currency, "income - commitments - variable"),
            Fact(f"{m}.{s}.trough", c.trough, currency, "balance just before payday"),
            Fact(f"{m}.{s}.headroom", c.headroom, currency, "trough - liquidity floor"),
        ]
    lowest = forecast.lowest
    facts += [
        Fact(f"{s}.lowest_headroom", lowest.headroom, currency, "min headroom over the horizon"),
        Fact(f"{s}.lowest_trough", lowest.trough, currency, "trough in the binding month"),
        Fact(f"{s}.binding_month", str(lowest.month), "month", "month of the lowest headroom"),
    ]
    return tuple(facts)
