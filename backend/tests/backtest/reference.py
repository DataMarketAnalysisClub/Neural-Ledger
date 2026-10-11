from __future__ import annotations

import math
import random
from collections import Counter
from fractions import Fraction

from neural_ledger.domain.finance.estimation import quantile
from neural_ledger.domain.finance.params import FC_0_1
from neural_ledger.domain.shared.month import Month
from neural_ledger.domain.shared.numbers import round_half_up
from tests.fixtures.stochastic import SEASONAL_MONTH, Lognormal, StochasticSpec, _round

BASE_SEED = 810_018
DEFAULT_TRIALS = 20_000


def exact_continuous_rank(n: int, q: Fraction, upper: bool) -> Fraction | None:
    position = q * (n - 1)
    if position.denominator != 1:
        return None
    rank = position.numerator + 1
    return Fraction(rank if upper else n + 1 - rank, n + 1)


def exact_continuous_rank_text(n: int, q: Fraction, upper: bool) -> str | None:
    probability = exact_continuous_rank(n, q, upper)
    return None if probability is None else f"{probability * (n + 1)}/{n + 1}"


def _cell(dist: Lognormal, spec: StochasticSpec, n: int, q: Fraction, upper: bool, trials: int, seed: int) -> dict:
    rng = random.Random(seed)
    hits = 0
    for _ in range(trials):
        history = [_round(spec, dist.draw(rng)) for _ in range(n)]
        future = _round(spec, dist.draw(rng))
        bound = round_half_up(quantile(history, q))
        hits += future <= bound if upper else future >= bound
    probability = hits / trials
    return {
        "median": dist.median, "sigma": str(dist.sigma), "window_n": n,
        "trials": trials, "hits": hits, "expected": round(probability, 6),
        "mc_se": round(math.sqrt(probability * (1 - probability) / trials), 6), "seed": seed,
    }


def _pooled(cells: dict[str, dict]) -> dict:
    total = sum(cell["observed_n"] for cell in cells.values())
    expected = sum(cell["observed_n"] * cell["hits"] / cell["trials"] for cell in cells.values()) / total
    variance = sum(
        (cell["observed_n"] / total) ** 2 * (cell["hits"] / cell["trials"])
        * (1 - cell["hits"] / cell["trials"]) / cell["trials"]
        for cell in cells.values()
    )
    return {"expected": round(expected, 6), "mc_se": round(math.sqrt(variance), 6), "observed_n": total}


def finite_sample_reference(
    spec: StochasticSpec,
    cycles: tuple[Month, ...],
    spend_weights: Counter[tuple[str, int, str]],
    income_weights: Counter[tuple[str, int]],
    spend_hits: Counter[tuple[str, int, str]],
    income_hits: Counter[tuple[str, int]],
    trials: int,
) -> dict:
    if trials < 1:
        raise ValueError("reference_trials must be positive")
    spend_cells: dict[str, dict] = {}
    income_cells: dict[str, dict] = {}
    cell_index = 0
    for (grid, origin, category), weight in sorted(spend_weights.items()):
        window = cycles[max(0, origin - FC_0_1.spend_window_months):origin]
        history_n = sum(cycle.month != SEASONAL_MONTH for cycle in window)
        key = f"{grid}.{origin}.{category}"
        spend_cells[key] = {
            **_cell(spec.spend[category], spec, history_n, Fraction(FC_0_1.variable_spend_percentile, 100),
                    True, trials, BASE_SEED + cell_index),
            "grid": grid, "origin": origin, "category": category, "observed_n": weight,
            "observed_hits": spend_hits[(grid, origin, category)],
        }
        cell_index += 1
    for (grid, origin), weight in sorted(income_weights.items()):
        window = cycles[max(0, origin - FC_0_1.spend_window_months):origin]
        assert spec.freelance is not None
        key = f"{grid}.{origin}"
        income_cells[key] = {
            **_cell(spec.freelance, spec, len(window), Fraction(FC_0_1.conservative_income_percentile, 100),
                    False, trials, BASE_SEED + cell_index),
            "grid": grid, "origin": origin, "observed_n": weight,
            "observed_hits": income_hits[(grid, origin)],
        }
        cell_index += 1
    grids = sorted({grid for grid, _, _ in spend_weights} | {grid for grid, _ in income_weights})
    return {
        "method": "type-7 quantile of independently rounded lognormal draws, then round_half_up; independent future draw",
        "base_seed": BASE_SEED, "trials_per_cell": trials, "rounding_step": spec.step,
        "cells": {"spend_p80": spend_cells, "freelance_income_p20": income_cells},
        "pooled": {
            grid: {
                "spend_p80": _pooled({key: cell for key, cell in spend_cells.items() if cell["grid"] == grid}),
                "freelance_income_p20": _pooled({key: cell for key, cell in income_cells.items() if cell["grid"] == grid}),
            }
            for grid in grids
        },
        "exact_continuous": {
            "spend_p80_n6": exact_continuous_rank_text(6, Fraction(4, 5), True),
            "spend_p80_n11": exact_continuous_rank_text(11, Fraction(4, 5), True),
            "freelance_income_p20_n6": exact_continuous_rank_text(6, Fraction(1, 5), False),
        },
        "assumptions": [
            "Each cell uses its category's actual median and sigma; freelance income uses its own distribution.",
            "Independent, identically distributed non-December historical and future draws within a cell; 100 CLP rounding is applied to each draw.",
            "Observed origin/category counts supply pooling weights; MC standard errors cover only independent reference simulations, not uncertainty in clustered observed hits.",
            "Exact continuous order-statistic fractions apply only where type-7 selects an order statistic; interpolation and rounded ties are distribution-dependent.",
        ],
    }
