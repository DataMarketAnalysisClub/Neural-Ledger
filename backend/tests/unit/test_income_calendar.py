"""ADR-040 §8: income per projected cycle. An empty calendar is the observed income in every cycle."""

from __future__ import annotations

from fractions import Fraction

import pytest

from neural_ledger.domain.finance.model import IncomeModel, IncomeStep, Scenario
from neural_ledger.domain.ledger.entities import IncomeType
from neural_ledger.domain.shared.month import Month

OBSERVED = IncomeModel(IncomeType.SALARIED, 1_075_000, 1_000_000, Fraction(1, 10), "percentile")


@pytest.mark.parametrize("scenario", list(Scenario))
def test_without_a_calendar_every_cycle_is_the_observed_income(scenario):
    expected = 1_075_000 if scenario is Scenario.TYPICAL else 1_000_000
    assert {OBSERVED.for_month(scenario, Month(2026, 10).plus(k)) for k in range(48)} == {expected}


def test_a_step_lasts_until_the_next_one_and_the_months_before_stay_observed():
    model = IncomeModel(
        IncomeType.SALARIED, 1_075_000, 1_000_000, Fraction(1, 10), "percentile",
        (IncomeStep(Month(2026, 11), 1_275_000, 1_000_000), IncomeStep(Month(2027, 4), 1_375_000, 1_200_000)),
    )
    assert model.for_month(Scenario.TYPICAL, Month(2026, 10)) == 1_075_000
    assert model.for_month(Scenario.TYPICAL, Month(2026, 11)) == 1_275_000
    assert model.for_month(Scenario.CONSERVATIVE, Month(2027, 3)) == 1_000_000
    assert model.for_month(Scenario.STRESS, Month(2027, 4)) == 1_200_000
    assert model.for_month(Scenario.TYPICAL, Month(2030, 12)) == 1_375_000  # any horizon, a credit's full term too


def test_steps_must_be_in_order():
    with pytest.raises(ValueError):
        IncomeModel(IncomeType.SALARIED, 1, 1, Fraction(0), "percentile", (IncomeStep(Month(2027, 1), 1, 1), IncomeStep(Month(2026, 1), 1, 1)))
