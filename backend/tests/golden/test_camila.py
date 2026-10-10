"""Golden answers E01-E11 (Financial Core design, section 6). These ARE the demo script.

If a number here changes, either the engine broke or the calibration changed: both need a
team decision and a new params_version.
"""

from __future__ import annotations

import pytest

from neural_ledger.domain.finance.capacity import assess_capacity
from neural_ledger.domain.finance.forecast import Recurring, Scenario, project
from neural_ledger.domain.finance.permitted import derive_permitted_profile
from neural_ledger.domain.finance.plan import size_plan
from neural_ledger.domain.finance.profile import RiskProfile
from neural_ledger.domain.finance.purchase import (
    AlternativeKind,
    Verdict,
    simulate_purchase,
)
from neural_ledger.domain.finance.surplus import protected_surplus
from neural_ledger.domain.shared.month import Month

pytestmark = pytest.mark.golden
DEC_2026, JAN_2027 = Month(2026, 12), Month(2027, 1)


def test_e01_conservative_path_and_december_crunch(camila, params):
    f = project(camila, params, Scenario.CONSERVATIVE, 6)
    assert [c.commitments for c in f.cycles] == [990_000, 990_000, 640_000, 640_000, 640_000, 640_000]
    assert [c.variable for c in f.cycles] == [900_000, 1_470_000, 900_000, 900_000, 900_000, 900_000]
    assert [c.available for c in f.cycles] == [-90_000, -660_000, 260_000, 260_000, 260_000, 260_000]
    assert [c.trough for c in f.cycles] == [830_000, 170_000, 430_000, 690_000, 950_000, 1_210_000]
    assert (f.lowest.month, f.lowest.headroom, f.lowest.trough) == (DEC_2026, 20_000, 170_000)
    typical = project(camila, params, Scenario.TYPICAL, 6)
    assert [c.trough for c in typical.cycles] == [1_010_000, 644_000, 1_084_000, 1_524_000, 1_964_000, 2_404_000]


def test_e02_laptop_cost(camila, params):
    q = simulate_purchase(camila, params, 400_000, 12, DEC_2026).quote
    assert (q.installment, q.total_cost, q.total_interest) == (38_995, 467_940, 67_940)
    assert round(float(q.effective_annual_rate), 3) == 0.345
    assert q.rate_assumed


def test_e03_laptop_fits_typical_only(camila, params):
    sim = simulate_purchase(camila, params, 400_000, 12, DEC_2026)
    assert sim.verdict is Verdict.FITS_TYPICAL_ONLY
    cons = sim.impact(Scenario.CONSERVATIVE)
    assert (cons.binding_month_after, cons.trough_after_in_binding_month, cons.lowest_headroom_after) == (DEC_2026, 131_005, -18_995)
    assert sim.impact(Scenario.TYPICAL).trough_after_in_binding_month == 605_005


def test_e04_alternatives(camila, params):
    alts = {a.kind: a for a in simulate_purchase(camila, params, 400_000, 12, DEC_2026).alternatives}
    assert alts[AlternativeKind.DEFER_START].first_installment_month == JAN_2027
    assert AlternativeKind.CHANGE_INSTALLMENTS not in alts  # 24 cuotas (22,365) still breaches
    assert alts[AlternativeKind.REDUCE_AMOUNT].amount == 205_000


def test_e05_capacity(camila, params):
    a = assess_capacity(camila, params)
    factors = {f.name: f for f in a.factors}
    assert a.level is RiskProfile.CONSERVATIVE and a.binding_factors == ("conservative_headroom",)
    assert round(factors["conservative_headroom"].value, 2) == 0.13
    assert round(factors["reserve_coverage"].value, 2) == 1.14 and factors["reserve_coverage"].band.value == "medium"
    assert factors["income_stability"].value == 0 and factors["income_stability"].band.value == "high"
    assert round(factors["debt_service"].value, 3) == 0.219 and factors["debt_service"].band.value == "medium"
    assert round(factors["stress_coverage"].value, 2) == 0.93 and factors["stress_coverage"].band.value == "medium"


def test_e06_permitted_profile(camila, params):
    p = derive_permitted_profile(RiskProfile.AGGRESSIVE, assess_capacity(camila, params), camila)
    assert p.permitted is RiskProfile.CONSERVATIVE


@pytest.mark.parametrize("profile, amount", [("conservative", 100_000), ("moderate", 150_000), ("aggressive", 200_000)])
def test_e07_savings_rule(camila, params, profile, amount):
    plan = size_plan(camila, params, RiskProfile(profile))
    assert (plan.amount, plan.start_month, plan.lowest_available_in_window) == (amount, JAN_2027, 260_000)


def test_e08_allocation(camila, params):
    plan = size_plan(camila, params, RiskProfile.CONSERVATIVE)
    assert [(a.bucket, a.monthly_amount) for a in plan.allocation] == [("goal:trip", 100_000)]
    reserve = next(r for r in plan.requirements if r.bucket == "reserve")
    assert (reserve.required_monthly, reserve.funded_monthly, reserve.funded_from) == (101_458, 0, Month(2027, 10))
    trip = plan.goal_status[0]
    assert (trip.projected_completion, trip.on_track) == (Month(2027, 9), True)


def test_e09_protected_surplus_with_plan(camila, params):
    plan = size_plan(camila, params, RiskProfile.CONSERVATIVE).as_recurring()
    result = protected_surplus(camila, params, 6, plan)
    assert (result.protected_surplus, result.binding_month) == (20_000, DEC_2026)
    assert [f.amount for f in result.monthly_free_flow if f.month >= JAN_2027] == [160_000] * 4


def test_e10_plan_if_laptop_deferred_to_january(camila, params):
    sim = simulate_purchase(camila, params, 400_000, 12, JAN_2027)
    assert sim.verdict is Verdict.FITS_ALL
    laptop = Recurring(sim.quote.installment, JAN_2027, JAN_2027.plus(11))
    plan = size_plan(camila, params, RiskProfile.CONSERVATIVE, purchases=(laptop,))
    assert (plan.amount, plan.lowest_available_in_window) == (80_000, 221_005)


def test_e11_stress(camila, params):
    stress = project(camila, params, Scenario.STRESS, 6)
    assert stress.cycle(DEC_2026).trough == -130_000
    factors = {f.name: f for f in assess_capacity(camila, params).factors}
    assert round(factors["stress_coverage"].value, 2) == 0.93
