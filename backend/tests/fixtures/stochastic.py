"""Opt-in seeded stochastic mode for the synthetic ledger generator (docs/SCOPE.md F16, ADR-015).

Synthetic-only modelling choice, not a claim about real spending: each category's per-cycle
variable spend is an independent lognormal draw (median, sigma), December cycles are then
multiplied by `seasonal_factor`, and a freelancer's per-cycle income is another lognormal
draw. Totals are rounded to `step` (at least one step, so every cycle has spend). The calendar
is `n_cycles` pay cycles from `first_cycle`; as_of is the eve of the last cycle's payday.

Because the distributions are known, the backtest (tests/backtest) can compare what the
stage-1 estimators recover from a ledger with the true parameters and with the realized
values of later cycles. Standard library only; this module must not import ledger_generator
(it imports this one).
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction
from statistics import NormalDist

from neural_ledger.domain.shared.month import Month

CATEGORIES = ("groceries", "dining", "transport", "shopping", "utilities", "health")  # = ledger_generator.SPEND_LAYOUT
SEASONAL_MONTH = 12  # FC_0_1.seasonal_months


@dataclass(frozen=True)
class Lognormal:
    """X = median * exp(sigma * Z), Z standard normal. `median` in minor units."""

    median: int
    sigma: Fraction

    def __post_init__(self) -> None:
        if isinstance(self.median, bool) or not isinstance(self.median, int) or self.median <= 0:
            raise ValueError("median must be a positive integer amount")
        if not isinstance(self.sigma, Fraction) or self.sigma <= 0:
            raise ValueError("sigma must be a positive Fraction")

    def draw(self, rng: random.Random) -> float:
        return rng.lognormvariate(math.log(self.median), float(self.sigma))

    def quantile(self, q: float) -> float:
        return self.median * math.exp(float(self.sigma) * NormalDist().inv_cdf(q))

    def cv(self) -> float:
        return math.sqrt(math.expm1(float(self.sigma) ** 2))


@dataclass(frozen=True)
class StochasticSpec:
    first_cycle: Month
    n_cycles: int
    spend: Mapping[str, Lognormal]
    seasonal_factor: Fraction = Fraction(49, 30)
    freelance: Lognormal | None = None
    step: int = 100

    def __post_init__(self) -> None:
        if isinstance(self.n_cycles, bool) or not isinstance(self.n_cycles, int) or self.n_cycles < 7:
            raise ValueError("n_cycles must be an integer >= 7 (6 cycles of history and one to evaluate)")
        if set(self.spend) != set(CATEGORIES):
            raise ValueError(f"spend must define exactly the categories {CATEGORIES}")
        if not all(isinstance(d, Lognormal) for d in self.spend.values()):
            raise ValueError("every spend distribution must be a Lognormal")
        if self.freelance is not None and not isinstance(self.freelance, Lognormal):
            raise ValueError("freelance must be a Lognormal or None")
        if not isinstance(self.seasonal_factor, Fraction) or self.seasonal_factor < 1:
            raise ValueError("seasonal_factor must be a Fraction >= 1")
        if isinstance(self.step, bool) or not isinstance(self.step, int) or self.step <= 0:
            raise ValueError("step must be a positive integer")


def _round(spec: StochasticSpec, value: float) -> int:
    return max(spec.step, math.floor(value / spec.step + 0.5) * spec.step)


def draw_spend(spec: StochasticSpec, rng: random.Random, cycles: tuple[Month, ...]) -> dict[str, dict[Month, int]]:
    """Per category, per cycle: a lognormal draw, times the seasonal factor in December."""
    out: dict[str, dict[Month, int]] = {}
    for category in CATEGORIES:
        dist = spec.spend[category]
        out[category] = {}
        for cycle in cycles:
            value = dist.draw(rng)
            if cycle.month == SEASONAL_MONTH:
                value *= float(spec.seasonal_factor)
            out[category][cycle] = _round(spec, value)
    return out


def draw_income(spec: StochasticSpec, rng: random.Random, cycles: tuple[Month, ...]) -> dict[Month, int]:
    if spec.freelance is None:
        raise ValueError("the spec has no freelance income distribution")
    return {cycle: _round(spec, spec.freelance.draw(rng)) for cycle in cycles}


def true_parameters(spec: StochasticSpec) -> dict:
    """What a perfect estimator would recover (money rounded to the unit, ratios to 6 places)."""
    spend = {
        c: {"p50": round(d.quantile(0.5)), "p80": round(d.quantile(0.8)), "sigma": str(d.sigma)}
        for c, d in sorted(spec.spend.items())
    }
    out: dict = {"spend": spend, "seasonal_factor": str(spec.seasonal_factor)}
    if spec.freelance is not None:
        f = spec.freelance
        out["income"] = {"p50": round(f.quantile(0.5)), "p20": round(f.quantile(0.2)), "cv": round(f.cv(), 6), "sigma": str(f.sigma)}
    return out
