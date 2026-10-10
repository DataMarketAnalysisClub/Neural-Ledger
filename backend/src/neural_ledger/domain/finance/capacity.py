"""Capacity engine (Financial Core 4.7): what the finances permit. Weakest band wins.

Debt service counts only debt (cuotas, loans), not rent or subscriptions: that is the
definition that reproduces golden E05 (21.9%); see docs/SCOPE.md, issue F1.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from fractions import Fraction

from ..shared.envelope import Fact
from ..shared.errors import InsufficientData
from ..shared.month import month_range
from ..shared.numbers import round_half_up
from .forecast import Scenario, project
from .model import CommitmentType, FinancialModel
from .params import FinanceParams
from .profile import RiskProfile


class Band(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

    @property
    def rank(self) -> int:
        return {"low": 0, "medium": 1, "high": 2}[self.value]


_PROFILE_FOR_BAND = {Band.LOW: RiskProfile.CONSERVATIVE, Band.MEDIUM: RiskProfile.MODERATE, Band.HIGH: RiskProfile.AGGRESSIVE}

FACTOR_ORDER = ("reserve_coverage", "income_stability", "debt_service", "conservative_headroom", "stress_coverage")


@dataclass(frozen=True, slots=True)
class CapacityFactor:
    name: str
    value: float
    band: Band
    measure: str


@dataclass(frozen=True, slots=True)
class CapacityAssessment:
    level: RiskProfile
    binding_factor: str
    binding_factors: tuple[str, ...]
    factors: tuple[CapacityFactor, ...]
    essentials_monthly: int
    reserve_minimum: int
    reserve_target: int


def band_up(value: Fraction, bands: tuple[Fraction, Fraction]) -> Band:
    low_below, high_from = bands
    return Band.LOW if value < low_below else Band.HIGH if value >= high_from else Band.MEDIUM


def band_down(value: Fraction, bands: tuple[Fraction, Fraction]) -> Band:
    high_below, low_above = bands
    return Band.HIGH if value < high_below else Band.LOW if value > low_above else Band.MEDIUM


def essentials_exact(model: FinancialModel, params: FinanceParams) -> Fraction:
    """Rent + essential categories at P80 (no seasonality) + average debt service over the horizon."""
    months = month_range(model.first_cycle, params.dashboard_horizon_months)
    rent = Fraction(sum(model.commitments_due(m, frozenset({CommitmentType.RENT})) for m in months), len(months))
    debt = Fraction(sum(model.debt_service_due(m) for m in months), len(months))
    return model.spend.essentials_p80() + rent + debt


def assess_capacity(model: FinancialModel, params: FinanceParams) -> CapacityAssessment:
    essentials = essentials_exact(model, params)
    if essentials <= 0:
        # every coverage factor is a ratio over essentials: unknown, not infinite (hard rule H4)
        raise InsufficientData(("spend.essentials",), "monthly essentials are zero, so capacity cannot be assessed")
    horizon = params.dashboard_horizon_months
    months = month_range(model.first_cycle, horizon)

    reserve_cov = Fraction(model.balances.reserve) / essentials
    cv = Fraction(model.income.cv)
    income = model.income.conservative
    peak_debt = max(model.debt_service_due(m) for m in months)
    debt_ratio = Fraction(peak_debt, income) if income > 0 else Fraction(10)
    conservative = project(model, params, Scenario.CONSERVATIVE, horizon)
    headroom_ratio = Fraction(conservative.lowest.headroom, params.liquidity_floor)
    stress = project(model, params, Scenario.STRESS, horizon)
    shortfall = max(0, -stress.lowest.headroom)
    stress_cov = Fraction(max(0, model.balances.reserve - shortfall)) / essentials

    factors = (
        CapacityFactor("reserve_coverage", float(reserve_cov), band_up(reserve_cov, params.reserve_coverage_bands), "reserve / monthly essentials"),
        CapacityFactor("income_stability", float(cv), band_down(cv, params.income_cv_bands), "coefficient of variation of monthly income"),
        CapacityFactor("debt_service", float(debt_ratio), band_down(debt_ratio, params.debt_service_bands), "peak monthly debt payments / conservative income"),
        CapacityFactor("conservative_headroom", float(headroom_ratio), band_up(headroom_ratio, params.headroom_ratio_bands), "lowest conservative headroom / floor"),
        CapacityFactor("stress_coverage", float(stress_cov), band_up(stress_cov, params.stress_coverage_bands), "reserve left after the stress shortfall, in months of essentials"),
    )
    weakest = min(f.band.rank for f in factors)
    binding = tuple(f.name for f in factors if f.band.rank == weakest)
    level = _PROFILE_FOR_BAND[next(f.band for f in factors if f.band.rank == weakest)]
    return CapacityAssessment(
        level=level,
        binding_factor=binding[0],
        binding_factors=binding,
        factors=factors,
        essentials_monthly=round_half_up(essentials),
        reserve_minimum=round_half_up(params.reserve_min_months * essentials),
        reserve_target=round_half_up(params.reserve_target_months * essentials),
    )


def capacity_facts(a: CapacityAssessment, currency: str) -> tuple[Fact, ...]:
    facts = [
        Fact("capacity.level", a.level.value, "profile", "weakest factor band"),
        Fact("capacity.binding_factor", a.binding_factor, "factor", "first factor at the weakest band"),
        Fact("essentials.monthly", a.essentials_monthly, currency, "rent + essential P80 + average debt service"),
        Fact("reserve.minimum", a.reserve_minimum, currency, "reserve_min_months x essentials"),
        Fact("reserve.target", a.reserve_target, currency, "reserve_target_months x essentials"),
    ]
    for f in a.factors:
        facts += [
            Fact(f"capacity.{f.name}.value", round(f.value, 4), "ratio", f.measure),
            Fact(f"capacity.{f.name}.band", f.band.value, "band", "parameter register bands"),
        ]
        if f.name == "debt_service":
            facts.append(Fact("capacity.debt_service.pct", round(f.value * 100, 1), "%", f.measure))
    return tuple(facts)
