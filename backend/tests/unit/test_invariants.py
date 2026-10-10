"""Invariants that must hold for ANY data (Financial Core section 8), checked on perturbed fixtures.

Standard library random with a fixed seed: reproducible, no extra dependency.
"""

from __future__ import annotations

import random
from dataclasses import replace

import pytest

from neural_ledger.domain.finance.forecast import Recurring, Scenario, project
from neural_ledger.domain.finance.installments import quote
from neural_ledger.domain.finance.plan import size_plan
from neural_ledger.domain.finance.profile import RiskProfile
from neural_ledger.domain.shared.month import Month


def variants(model, n=25, seed=7):
    rng = random.Random(seed)
    for _ in range(n):
        balances = replace(model.balances, checking=rng.randrange(0, 3_000_000, 1_000), reserve=rng.randrange(0, 5_000_000, 1_000))
        income = replace(model.income, typical=rng.randrange(900_000, 3_000_000, 10_000))
        income = replace(income, conservative=min(income.typical, rng.randrange(800_000, 3_000_000, 10_000)))
        yield replace(model, balances=balances, income=income)


@pytest.mark.parametrize("index", range(25))
def test_invariants(camila, params, index):
    model = list(variants(camila))[index]
    cons = project(model, params, Scenario.CONSERVATIVE, 12)
    typ = project(model, params, Scenario.TYPICAL, 12)
    # conservative is never better than typical
    assert all(c.trough <= t.trough for c, t in zip(cons.cycles, typ.cycles))
    # a purchase never raises any trough
    laptop = Recurring(38_995, Month(2026, 12), Month(2027, 11))
    with_purchase = project(model, params, Scenario.CONSERVATIVE, 12, purchases=(laptop,))
    assert all(a.trough <= b.trough for a, b in zip(with_purchase.cycles, cons.cycles))
    # plans: multiples of 10,000, never breach (H5), monotone in the profile
    amounts = []
    for profile in RiskProfile:
        plan = size_plan(model, params, profile)
        assert plan.amount % params.rule_rounding == 0
        if plan.amount:
            horizon = model.first_cycle.months_until(plan.start_month.plus(params.check_horizon_months - 1)) + 1
            assert not project(model, params, Scenario.CONSERVATIVE, horizon, plan=plan.as_recurring()).breaches
        amounts.append(plan.amount)
    assert amounts == sorted(amounts)
    # adding a purchase never raises the plan
    assert size_plan(model, params, RiskProfile.CONSERVATIVE, purchases=(laptop,)).amount <= amounts[0]


def test_same_input_same_output(camila, params):
    assert project(camila, params, Scenario.CONSERVATIVE, 12) == project(camila, params, Scenario.CONSERVATIVE, 12)


def test_p80_is_never_below_p50(camila):
    assert all(c.p80 >= c.p50 for c in camila.spend.categories)


@pytest.mark.parametrize("n", [3, 6, 12, 18, 24])
def test_installments_add_up(params, n):
    q = quote(400_000, n, params.default_monthly_rate, rate_assumed=True)
    assert q.total_cost == q.installment * n and q.total_interest == q.total_cost - 400_000
