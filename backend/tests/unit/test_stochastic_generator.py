"""Opt-in stochastic generator mode (tests/fixtures/stochastic.py, docs/SCOPE.md F16)."""

from __future__ import annotations

import math
import random
from collections import defaultdict
from dataclasses import replace
from datetime import date
from fractions import Fraction

import pytest

from neural_ledger.domain.finance.paycycle import cycle_of
from neural_ledger.domain.shared.month import Month
from tests.conftest import LEDGERS
from tests.fixtures.ledger_generator import PERSONAS, SPEND_LAYOUT, GeneratorConfig, generate_ledger_with_truth, render
from tests.fixtures.stochastic import CATEGORIES, Lognormal, StochasticSpec, draw_spend, true_parameters

SPEND = {c: Lognormal(100_000, Fraction(1, 4)) for c in CATEGORIES}
SPEC = StochasticSpec(Month(2025, 4), 21, SPEND)


def _config(seed: int, **changes) -> GeneratorConfig:
    base = GeneratorConfig("stoch", seed, (), bonus=0, savings_opening=50_000_000, savings_buckets=None, strict_balances=False, stochastic=SPEC)
    return replace(base, **changes)


def test_categories_match_the_generator_layout():
    assert CATEGORIES == tuple(SPEND_LAYOUT)


@pytest.mark.parametrize("persona", list(PERSONAS))
def test_calibrated_personas_are_byte_identical(persona):
    assert render(persona) == (LEDGERS / f"{persona}.json").read_text(encoding="utf-8")


def test_calibrated_configs_record_no_truth():
    assert generate_ledger_with_truth(PERSONAS["camila"])[1] == {}


def test_same_seed_same_ledger_and_different_seed_different_ledger():
    first, second, other = (generate_ledger_with_truth(_config(s)) for s in (7, 7, 8))
    assert first == second
    assert first[0]["transactions"] != other[0]["transactions"]


def test_stochastic_calendar_and_truth_match_the_ledger():
    raw, truth = generate_ledger_with_truth(_config(11))
    assert raw["as_of"] == "2026-12-30"
    dates = [date.fromisoformat(t["date"]) for t in raw["transactions"]]
    assert cycle_of(min(dates)) == Month(2025, 4) and max(dates) <= date(2026, 12, 30)
    totals: dict[str, dict[Month, int]] = defaultdict(lambda: defaultdict(int))
    for t, day in zip(raw["transactions"], dates):
        if t["category"] in CATEGORIES:
            assert t["kind"] == "purchase" and t["amount"] < 0
            totals[t["category"]][cycle_of(day)] -= t["amount"]
    assert {c: dict(v) for c, v in totals.items()} == truth["spend"]
    assert set(truth) == {"spend"}  # salaried: income is the contracted salary, not drawn


def test_freelance_income_is_drawn_and_recorded():
    spec = replace(SPEC, freelance=Lognormal(1_800_000, Fraction(3, 10)))
    raw, truth = generate_ledger_with_truth(_config(5, salary=None, stochastic=spec))
    credits: dict[Month, int] = defaultdict(int)
    for t in raw["transactions"]:
        if t["kind"] == "income":
            credits[cycle_of(date.fromisoformat(t["date"]))] += t["amount"]
    assert dict(credits) == truth["income"]
    assert raw["income_profile"]["type"] == "freelance"


def test_freelance_without_a_distribution_is_rejected():
    with pytest.raises(ValueError):
        generate_ledger_with_truth(_config(1, salary=None))


@pytest.mark.parametrize(
    "build",
    [
        lambda: Lognormal(0, Fraction(1, 4)),
        lambda: Lognormal(True, Fraction(1, 4)),
        lambda: Lognormal(100_000, Fraction(0)),
        lambda: Lognormal(100_000, Fraction(-1, 4)),
        lambda: Lognormal(100_000, 0.25),
        lambda: replace(SPEC, n_cycles=6),
        lambda: replace(SPEC, spend={**SPEND, "gambling": Lognormal(1_000, Fraction(1, 4))}),
        lambda: replace(SPEC, spend={c: d for c, d in SPEND.items() if c != "health"}),
        lambda: replace(SPEC, spend={**SPEND, "health": 48_000}),
        lambda: replace(SPEC, seasonal_factor=Fraction(9, 10)),
        lambda: replace(SPEC, seasonal_factor=1.5),
        lambda: replace(SPEC, freelance=1_800_000),
        lambda: replace(SPEC, step=0),
    ],
)
def test_invalid_specs_raise(build):
    with pytest.raises(ValueError):
        build()


def test_december_draws_carry_the_seasonal_factor():
    cycles = (Month(2025, 11), Month(2025, 12))
    flat = draw_spend(replace(SPEC, seasonal_factor=Fraction(1)), random.Random(3), cycles)
    double = draw_spend(replace(SPEC, seasonal_factor=Fraction(2)), random.Random(3), cycles)
    for category in CATEGORIES:
        assert flat[category][cycles[0]] == double[category][cycles[0]]
        assert abs(double[category][cycles[1]] - 2 * flat[category][cycles[1]]) <= 2 * SPEC.step
        assert all(v % SPEC.step == 0 and v >= SPEC.step for v in (*flat[category].values(), *double[category].values()))


def test_large_sample_quantiles_approach_the_true_parameters():
    dist = Lognormal(100_000, Fraction(1, 4))
    rng = random.Random(20261010)
    draws = sorted(dist.draw(rng) for _ in range(4001))
    assert abs(draws[2000] / dist.quantile(0.5) - 1) < 0.02
    assert abs(draws[3200] / dist.quantile(0.8) - 1) < 0.03
    truth = true_parameters(replace(SPEC, freelance=dist))
    assert truth["spend"]["groceries"]["p50"] == 100_000
    assert truth["spend"]["groceries"]["p80"] == round(100_000 * math.exp(0.25 * 0.8416212335729143))
    assert truth["income"]["cv"] == round(math.sqrt(math.expm1(0.0625)), 6)
