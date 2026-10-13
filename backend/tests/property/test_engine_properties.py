"""Section 8 invariants of the stage-2 engines, on models ESTIMATED from random valid ledgers."""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from neural_ledger.domain.finance.estimation import estimate_model
from neural_ledger.domain.finance.forecast import Recurring, Scenario, project
from neural_ledger.domain.finance.installments import quote
from neural_ledger.domain.finance.params import FC_0_1
from neural_ledger.domain.finance.plan import size_plan
from neural_ledger.domain.finance.profile import RiskProfile
from neural_ledger.domain.finance.surplus import protected_surplus
from tests.property.strategies import PROPERTY_SETTINGS, raw_ledgers, snapshot_of

pytestmark = pytest.mark.property

KNOWN_PLAN_ISSUE = pytest.mark.xfail(
    strict=False,
    reason="false in general: see the minimal counterexamples in test_plan_counterexamples.py (team decision pending)",
)
PROFILES = (RiskProfile.CONSERVATIVE, RiskProfile.MODERATE, RiskProfile.AGGRESSIVE)
HORIZON = FC_0_1.check_horizon_months


def _model(raw):
    envelope = estimate_model(snapshot_of(raw), FC_0_1)
    assert envelope.ok, (envelope.status, envelope.missing, envelope.field)
    return envelope.data


purchases = st.tuples(
    st.integers(10, 2_000).map(lambda k: k * 1_000),
    st.sampled_from(FC_0_1.allowed_installments),
    st.integers(0, 6),
    st.sampled_from([Decimal("0"), Decimal("0.015"), Decimal("0.025")]),
)


def _overlay(model, purchase) -> Recurring:
    amount, n, offset, rate = purchase
    q = quote(amount, n, rate, rate_assumed=False)
    first = model.first_cycle.plus(offset)
    return Recurring(q.installment, first, first.plus(n - 1))


@PROPERTY_SETTINGS
@given(raw_ledgers())
def test_p80_is_never_below_p50(raw):
    assert all(c.p80 >= c.p50 >= 0 for c in _model(raw).spend.categories)


@PROPERTY_SETTINGS
@given(raw_ledgers())
def test_conservative_trough_never_above_typical(raw):
    model = _model(raw)
    conservative = project(model, FC_0_1, Scenario.CONSERVATIVE, HORIZON)
    typical = project(model, FC_0_1, Scenario.TYPICAL, HORIZON)
    assert all(c.trough <= t.trough for c, t in zip(conservative.cycles, typical.cycles))


@PROPERTY_SETTINGS
@given(raw_ledgers(), purchases)
def test_a_purchase_never_raises_a_trough_or_the_protected_surplus(raw, purchase):
    model = _model(raw)
    overlay = (_overlay(model, purchase),)
    for scenario in (Scenario.TYPICAL, Scenario.CONSERVATIVE):
        before = project(model, FC_0_1, scenario, HORIZON)
        after = project(model, FC_0_1, scenario, HORIZON, purchases=overlay)
        assert all(a.trough <= b.trough for a, b in zip(after.cycles, before.cycles))
    assert protected_surplus(model, FC_0_1, HORIZON, purchases=overlay).protected_surplus <= protected_surplus(model, FC_0_1, HORIZON).protected_surplus


@KNOWN_PLAN_ISSUE
@PROPERTY_SETTINGS
@given(raw_ledgers(), purchases, st.sampled_from(PROFILES))
def test_a_purchase_never_raises_the_plan(raw, purchase, profile):
    model = _model(raw)
    with_purchase = size_plan(model, FC_0_1, profile, purchases=(_overlay(model, purchase),))
    assert with_purchase.amount <= size_plan(model, FC_0_1, profile).amount


@PROPERTY_SETTINGS
@given(raw_ledgers(), st.sampled_from(PROFILES))
def test_no_plan_breaches_the_floor_and_rules_are_multiples_of_10k(raw, profile):
    model = _model(raw)
    plan = size_plan(model, FC_0_1, profile)
    assert plan.amount % FC_0_1.rule_rounding == 0
    if plan.amount:
        check = model.first_cycle.months_until(plan.start_month.plus(FC_0_1.check_horizon_months - 1)) + 1
        assert not project(model, FC_0_1, Scenario.CONSERVATIVE, check, plan=plan.as_recurring()).breaches  # H5


@PROPERTY_SETTINGS
@given(raw_ledgers())
def test_a_higher_profile_never_gives_a_smaller_rule(raw):
    model = _model(raw)
    amounts = [size_plan(model, FC_0_1, p).amount for p in PROFILES]
    assert amounts == sorted(amounts)


@PROPERTY_SETTINGS
@given(purchases)
def test_cuotas_add_up_exactly_to_the_total_cost(purchase):
    amount, n, _, rate = purchase
    q = quote(amount, n, rate, rate_assumed=False)
    assert q.installment * q.installments == q.total_cost
    assert q.total_cost - q.principal == q.total_interest
