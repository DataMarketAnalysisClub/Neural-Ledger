"""Golden answers E12-E14: same purchase, different answer (freelance income)."""

from __future__ import annotations

import pytest

from neural_ledger.domain.finance.capacity import assess_capacity
from neural_ledger.domain.finance.forecast import Scenario, project
from neural_ledger.domain.finance.plan import H2, size_plan
from neural_ledger.domain.finance.profile import RiskProfile
from neural_ledger.domain.finance.purchase import Verdict, simulate_purchase
from neural_ledger.domain.shared.month import Month

pytestmark = pytest.mark.golden


def test_e12_baseline_breach(diego, params):
    sim = simulate_purchase(diego, params, 400_000, 12, Month(2026, 12))
    assert sim.verdict is Verdict.BASELINE_BREACH
    assert sim.alternatives == ()
    assert project(diego, params, Scenario.CONSERVATIVE, 6).cycle(Month(2026, 12)).trough == -830_000


def test_e13_no_recurring_rule(diego, params):
    plan = size_plan(diego, params, RiskProfile.CONSERVATIVE)
    assert plan.amount == 0 and plan.hard_rules_triggered == (H2,)
    f = project(diego, params, Scenario.CONSERVATIVE, 8)
    # Jan-May 2027 = -240,000; June is -195,000 because the phone cuotas end in May (doc says -240,000)
    assert [c.available for c in f.cycles[2:]] == [-240_000] * 5 + [-195_000]


def test_e14_capacity(diego, params):
    a = assess_capacity(diego, params)
    assert a.level is RiskProfile.CONSERVATIVE
    # The design doc lists income stability and headroom; stress coverage is also low (0.0 months).
    assert {"income_stability", "conservative_headroom"} <= set(a.binding_factors)
