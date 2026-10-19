"""ADR-040: with a constant salary declared as is nothing changes, and a declaration never lifts the conservative
income above what the statements support."""

from __future__ import annotations

from datetime import date

import pytest
from hypothesis import given
from hypothesis import strategies as st

from neural_ledger.domain.shared.month import Month
from tests.unit import test_income_memory as fixture

from .strategies import PROPERTY_SETTINGS

pytestmark = pytest.mark.property

SALARIES = st.integers(min_value=400_000, max_value=5_000_000)


@PROPERTY_SETTINGS
@given(salary=SALARIES, others=st.booleans())
def test_a_constant_salary_declared_as_is_changes_nothing(salary, others):
    snapshot = fixture.ledger(Month(2026, 9), {Month(2025, 9).plus(k): salary for k in range(13)}, others=others)
    model, result = fixture.overlay(snapshot, [fixture.declared(1, salary, "2025-09")])
    assert result.applied and result.warnings == ()
    assert fixture.income(result, "2026-10") == fixture.income(result, "2028-01") == (model.income.typical, model.income.conservative)


@PROPERTY_SETTINGS
@given(salary=SALARIES, declared=st.integers(min_value=1, max_value=100_000_000))
def test_an_unsupported_change_never_lifts_the_conservative_income(salary, declared):
    snapshot = fixture.ledger(Month(2026, 9), {Month(2025, 9).plus(k): salary for k in range(13)})
    versions = [fixture.declared(1, salary, "2025-09"), fixture.declared(2, declared, "2026-10", date(2026, 9, 15))]
    model, result = fixture.overlay(snapshot, versions)
    typical, conservative = fixture.income(result, "2026-11")
    assert typical == result.others_typical + declared
    assert conservative == result.others_conservative + min(declared, salary)
    assert conservative <= model.income.conservative  # never above the observed, whatever was declared
