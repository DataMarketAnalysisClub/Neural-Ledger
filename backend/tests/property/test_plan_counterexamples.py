"""Minimal counterexamples hypothesis found in size_plan (stage 2). PENDING A TEAM DECISION.

Both come from the start-month search in plan.py: a larger rule (higher profile) or a smaller
free flow (a purchase) can move the first feasible start month, and the amount at a later
start is not monotone. The engine is NOT changed here (the golden answers depend on it).

Proposed fix, to be evaluated by the team (not implemented): the profile is a ceiling; try
share(profile) and, if no start month is feasible, step down to the next lower share.
When the engine is fixed, these tests pass and xfail(strict=True) forces removing the marker.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from neural_ledger.domain.finance.params import FC_0_1
from neural_ledger.domain.finance.plan import H2, size_plan
from neural_ledger.domain.finance.profile import RiskProfile
from neural_ledger.domain.shared.month import Month
from tests.fixtures.ledger_generator import GeneratorConfig, generate_ledger
from tests.property.test_engine_properties import PROFILES, _model, _overlay

pytestmark = pytest.mark.property

_SANDBOX = dict(user_id="prop", seed=0, plans=(), savings_opening=50_000_000, savings_buckets=None, strict_balances=False)

# Available 55,200 every month and -596,636 in December: a rule must survive the next December.
PROFILE_CASE = GeneratorConfig(
    salary=1_290_000, rent=150_000, subscriptions=53_000,
    p80={"groceries": 10_000, "dining": 10_000, "transport": 11_000, "shopping": 400_000, "utilities": 400_000, "health": 200_000},
    **_SANDBOX,
)

# Without the purchase the rule starts in 2026-11, capped by Required (trip goal by 2027-09).
# The purchase pushes the start to 2027-01, fewer months remain to the deadline, Required rises.
PURCHASE_CASE = GeneratorConfig(
    salary=1_200_000, rent=150_000, subscriptions=5_000,
    p80={"groceries": 10_000, "dining": 79_000, "transport": 150_000, "shopping": 59_000, "utilities": 10_000, "health": 10_000},
    **_SANDBOX,
)
LAPTOP_LIKE = (1_505_000, 3, 0, Decimal("0"))  # 3 cuotas of 501,667 from 2026-11


def test_profile_case_is_what_the_engine_does_today():
    model = _model(generate_ledger(PROFILE_CASE))
    plans = [size_plan(model, FC_0_1, p) for p in PROFILES]
    assert [(p.amount, p.start_month) for p in plans] == [(20_000, Month(2027, 2)), (30_000, Month(2027, 6)), (0, None)]
    assert plans[2].hard_rules_triggered == (H2,)  # aggressive: 40,000 breaches before every next December


@pytest.mark.xfail(strict=True, reason="size_plan: a higher profile can give a smaller rule (no feasible start month); team decision pending")
def test_a_higher_profile_never_gives_a_smaller_rule__minimal_case():
    model = _model(generate_ledger(PROFILE_CASE))
    amounts = [size_plan(model, FC_0_1, p).amount for p in PROFILES]
    assert amounts == sorted(amounts)


def test_purchase_case_is_what_the_engine_does_today():
    model = _model(generate_ledger(PURCHASE_CASE))
    without = size_plan(model, FC_0_1, RiskProfile.CONSERVATIVE)
    with_purchase = size_plan(model, FC_0_1, RiskProfile.CONSERVATIVE, purchases=(_overlay(model, LAPTOP_LIKE),))
    assert (without.amount, without.start_month, without.required_monthly) == (80_000, Month(2026, 11), 81_819)
    assert (with_purchase.amount, with_purchase.start_month, with_purchase.required_monthly) == (90_000, Month(2027, 1), 100_000)


@pytest.mark.xfail(strict=True, reason="size_plan: a later start raises Required, so a purchase can raise the rule; team decision pending")
def test_a_purchase_never_raises_the_plan__minimal_case():
    model = _model(generate_ledger(PURCHASE_CASE))
    with_purchase = size_plan(model, FC_0_1, RiskProfile.CONSERVATIVE, purchases=(_overlay(model, LAPTOP_LIKE),))
    assert with_purchase.amount <= size_plan(model, FC_0_1, RiskProfile.CONSERVATIVE).amount
