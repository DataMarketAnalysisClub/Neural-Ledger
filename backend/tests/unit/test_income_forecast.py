"""ADR-049 §8: the projections read each cycle's income from the calendar, and capacity divides each month's debt
by that month's conservative income. Ledgers from test_income_memory (as_of 2026-09-29, first cycle 2026-10)."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

from neural_ledger.domain.finance.capacity import assess_capacity
from neural_ledger.domain.finance.estimation import estimate_model
from neural_ledger.domain.finance.forecast import project
from neural_ledger.domain.finance.income_memory import (
    RAISE_ASSUMED,
    SALARY_CONFLICT,
    overlay_facts,
    with_income_memory,
)
from neural_ledger.domain.finance.model import Commitment, CommitmentType, IncomeStep, Scenario
from neural_ledger.domain.finance.params import FC_0_1
from neural_ledger.domain.shared.month import Month

from .test_income_memory import BASE, SEPTEMBER, declared, ledger, overlay

RAISE = [declared(1, BASE, "2025-09"), declared(2, 1_200_000, "2026-10", date(2026, 9, 15))]


def incomes(model, scenario, horizon=4):
    return [c.income for c in project(model, FC_0_1, scenario, horizon).cycles]


def test_without_a_calendar_every_cycle_has_the_observed_income():
    model = estimate_model(SEPTEMBER, FC_0_1).data
    assert incomes(model, Scenario.TYPICAL) == [1_075_000] * 4
    assert incomes(model, Scenario.CONSERVATIVE) == incomes(model, Scenario.STRESS) == [1_000_000] * 4


def test_a_raise_reaches_the_forecast_from_the_cycle_it_funds():
    model, result = overlay(SEPTEMBER, RAISE)
    applied = with_income_memory(model, result)
    assert incomes(applied, Scenario.TYPICAL) == [1_075_000, 1_275_000, 1_275_000, 1_275_000]
    assert incomes(applied, Scenario.CONSERVATIVE) == [1_000_000] * 4  # not supported yet: RAISE_ASSUMED
    assert result.warnings == (RAISE_ASSUMED,)


def test_stress_uses_the_monthly_conservative_income_and_the_same_shock():
    model, result = overlay(SEPTEMBER, [declared(1, BASE, "2025-09"), declared(2, 900_000, "2026-10", date(2026, 9, 15))])
    applied = with_income_memory(model, result)
    stress = project(applied, FC_0_1, Scenario.STRESS, 4)
    assert [c.income for c in stress.cycles] == [1_000_000, 900_000, 900_000, 900_000]
    assert [c.shock for c in stress.cycles] == [c.shock for c in project(model, FC_0_1, Scenario.STRESS, 4).cycles]


def test_the_calendar_covers_a_credit_term_beyond_the_dashboard():
    model, result = overlay(SEPTEMBER, RAISE)
    assert incomes(with_income_memory(model, result), Scenario.TYPICAL, 60)[-1] == 1_275_000


def test_memory_joins_the_source_version_even_when_only_saved():
    model, result = overlay(SEPTEMBER, RAISE)
    assert with_income_memory(model, result).source_version == f"{model.source_version}+memory:{result.fingerprint}"
    late = ledger(Month(2026, 9), {Month(2026, 7): 0, Month(2026, 8): 0})
    model, result = overlay(late, [declared(1, BASE, "2025-09")])
    saved = with_income_memory(model, result)
    assert result.warnings == (SALARY_CONFLICT,) and saved.income == model.income and saved.source_version != model.source_version
    model, result = overlay(SEPTEMBER, [])
    assert with_income_memory(model, result) is model


def test_the_overlay_states_what_the_forecast_rests_on():
    model, result = overlay(ledger(Month(2026, 12), {Month(2026, 10): 1_200_000, Month(2026, 11): 1_200_000}), RAISE)
    facts = {f.key: f.value for f in overlay_facts(result, "CLP")}
    assert facts["income.others.typical"] == 75_000 and facts["income.others.conservative"] == 0
    assert facts["income.2027-01.declared_salary"] == 1_200_000 and facts["income.2027-01.supported_salary"] == 1_200_000
    _, saved = overlay(SEPTEMBER, [declared(1, 1_200_000, "2026-10", date(2026, 9, 15))])
    assert overlay_facts(saved, "CLP") == ()


def _with_debt(model, steps, debts):
    income = replace(model.income, monthly=tuple(steps))
    commitments = tuple(
        Commitment(f"loan_{m}", CommitmentType.LOAN, "CREDITO", amount, Month.parse(m), Month.parse(m)) for m, amount in debts
    )
    return replace(model, income=income, commitments=commitments)


def _debt_service(model):
    return next(f.value for f in assess_capacity(model, FC_0_1).factors if f.name == "debt_service")


def test_capacity_never_divides_one_month_by_another():
    model = estimate_model(SEPTEMBER, FC_0_1).data  # conservative 1,000,000
    steps = [IncomeStep(Month(2026, 10), 1_075_000, 1_000_000), IncomeStep(Month(2026, 12), 575_000, 500_000)]
    # 400,000 against 1,000,000 in October; nothing due once the income drops to 500,000
    assert _debt_service(_with_debt(model, steps, [("2026-10", 400_000)])) == 0.4  # not 400,000 / 500,000
    # 300,000 due in December against 500,000 binds, although October's debt is larger
    assert _debt_service(_with_debt(model, steps, [("2026-10", 400_000), ("2026-12", 300_000)])) == 0.6


def test_capacity_with_an_empty_calendar_is_the_peak_over_the_observed_income():
    model = estimate_model(SEPTEMBER, FC_0_1).data
    assert _debt_service(_with_debt(model, [], [("2026-10", 400_000), ("2026-12", 300_000)])) == 0.4


def test_a_constant_salary_declared_as_is_leaves_every_projection_and_capacity_unchanged():  # example A
    model, result = overlay(SEPTEMBER, [declared(1, BASE, "2025-09")])
    applied = with_income_memory(model, result)
    for scenario in Scenario:
        assert project(applied, FC_0_1, scenario, 12).cycles == project(model, FC_0_1, scenario, 12).cycles
    assert assess_capacity(applied, FC_0_1) == assess_capacity(model, FC_0_1)


def test_each_cycle_reads_its_own_step():
    model = estimate_model(SEPTEMBER, FC_0_1).data
    stepped = replace(model, income=replace(model.income, monthly=(IncomeStep(Month(2026, 11), 1_275_000, 900_000),)))
    assert incomes(stepped, Scenario.TYPICAL) == [1_075_000, 1_275_000, 1_275_000, 1_275_000]
    assert incomes(stepped, Scenario.CONSERVATIVE) == incomes(stepped, Scenario.STRESS) == [1_000_000, 900_000, 900_000, 900_000]
