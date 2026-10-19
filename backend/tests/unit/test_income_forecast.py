"""ADR-040 §8: the projections read each cycle's income from the calendar, and capacity divides each month's debt
by that month's conservative income. Ledgers from test_income_memory (as_of 2026-09-29, first cycle 2026-10)."""

from __future__ import annotations

from dataclasses import replace

from neural_ledger.domain.finance.capacity import assess_capacity
from neural_ledger.domain.finance.estimation import estimate_model
from neural_ledger.domain.finance.forecast import project
from neural_ledger.domain.finance.model import Commitment, CommitmentType, IncomeStep, Scenario
from neural_ledger.domain.finance.params import FC_0_1
from neural_ledger.domain.shared.month import Month

from .test_income_memory import SEPTEMBER


def incomes(model, scenario, horizon=4):
    return [c.income for c in project(model, FC_0_1, scenario, horizon).cycles]



def test_without_a_calendar_every_cycle_has_the_observed_income():
    model = estimate_model(SEPTEMBER, FC_0_1).data
    assert incomes(model, Scenario.TYPICAL) == [1_075_000] * 4
    assert incomes(model, Scenario.CONSERVATIVE) == incomes(model, Scenario.STRESS) == [1_000_000] * 4



def test_each_cycle_reads_its_own_step():
    model = estimate_model(SEPTEMBER, FC_0_1).data
    stepped = replace(model, income=replace(model.income, monthly=(IncomeStep(Month(2026, 11), 1_275_000, 900_000),)))
    assert incomes(stepped, Scenario.TYPICAL) == [1_075_000, 1_275_000, 1_275_000, 1_275_000]
    assert incomes(stepped, Scenario.CONSERVATIVE) == incomes(stepped, Scenario.STRESS) == [1_000_000, 900_000, 900_000, 900_000]


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

