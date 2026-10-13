from fractions import Fraction

from neural_ledger.adapters.outbound.fixtures.persona_source import PersonaFixtureSource
from neural_ledger.domain.finance.params import FC_0_1
from neural_ledger.domain.finance.plan import H2, size_plan
from neural_ledger.domain.finance.profile import RiskProfile
from neural_ledger.domain.shared.month import Month
from neural_ledger.domain.shared.serialization import to_primitive
from tests.conftest import DATA
from tests.contract.test_contracts import validate
from tests.fixtures.ledger_generator import generate_ledger
from tests.property.test_engine_properties import _model
from tests.property.test_plan_counterexamples import PROFILE_CASE, PURCHASE_CASE


def test_profile_ceiling_selects_the_largest_feasible_rule_and_actual_share():
    model = _model(generate_ledger(PROFILE_CASE))

    plan = size_plan(model, FC_0_1, RiskProfile.AGGRESSIVE)

    assert (plan.profile, plan.amount, plan.start_month, plan.share) == (
        RiskProfile.AGGRESSIVE, 30_000, Month(2027, 6), Fraction(3, 5),
    )
    assert plan.hard_rules_triggered == ()
    validate(to_primitive(plan), "outputs/savings_plan.schema.json")


def test_equal_amount_and_start_preserve_the_higher_profile_share():
    model = _model(generate_ledger(PURCHASE_CASE))

    plan = size_plan(model, FC_0_1, RiskProfile.AGGRESSIVE)

    assert (plan.amount, plan.start_month, plan.share) == (80_000, Month(2026, 11), Fraction(4, 5))
    validate(to_primitive(plan), "outputs/savings_plan.schema.json")


def test_conservative_camila_keeps_the_single_share_golden_rule():
    model = PersonaFixtureSource(DATA / "personas").load("camila")

    plan = size_plan(model, FC_0_1, RiskProfile.CONSERVATIVE)

    assert (plan.amount, plan.start_month, plan.share) == (100_000, Month(2027, 1), Fraction(2, 5))
    validate(to_primitive(plan), "outputs/savings_plan.schema.json")


def test_no_feasible_candidate_preserves_h2_and_ceiling_share():
    model = PersonaFixtureSource(DATA / "personas").load("diego")

    plan = size_plan(model, FC_0_1, RiskProfile.AGGRESSIVE)

    assert (plan.amount, plan.start_month, plan.share, plan.hard_rules_triggered) == (0, None, Fraction(4, 5), (H2,))
    validate(to_primitive(plan), "outputs/savings_plan.schema.json")
