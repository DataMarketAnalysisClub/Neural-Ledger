"""Acceptance test for stage 1: generated ledger -> estimators -> exactly the calibrated model.

The persona fixtures (data/personas) are the golden reference; data/ledgers is what the
generator (tests/fixtures/ledger_generator.py) wrote. E01-E14 also run on the estimated
models (tests/golden/conftest.py parametrizes them over both sources).
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from fractions import Fraction

import pytest

from neural_ledger.adapters.outbound.fixtures.persona_source import PersonaFixtureSource
from neural_ledger.domain.finance.estimation import estimate_model
from neural_ledger.domain.finance.forecast import Scenario, project
from neural_ledger.domain.finance.model import FinancialModel
from neural_ledger.domain.finance.paycycle import cycle_of
from neural_ledger.domain.shared.month import Month
from tests.conftest import DATA, LEDGERS
from tests.fixtures.ledger_generator import UNEXPECTED_EXPENSE, render

pytestmark = pytest.mark.golden
PERSONAS = ("camila", "diego")


def _comparable(model: FinancialModel) -> FinancialModel:
    """Everything the engines read, in a canonical order. Evidence ids and the source version
    are checked separately: the fixture has neither."""
    return replace(
        model,
        source_version="",
        commitments=tuple(sorted((replace(c, evidence_txn_ids=()) for c in model.commitments), key=lambda c: c.commitment_id)),
        spend=replace(model.spend, categories=tuple(sorted(model.spend.categories, key=lambda c: c.category))),
    )


@pytest.mark.parametrize("user", PERSONAS)
def test_estimators_reproduce_the_calibration_field_by_field(user, ledger_source, params):
    reference = PersonaFixtureSource(DATA / "personas").load(user)
    estimated = ledger_source.load(user)
    expected, actual = _comparable(reference), _comparable(estimated)
    for field in ("user_id", "currency", "as_of", "first_cycle", "balances", "income", "goals", "largest_one_off_expense"):
        assert getattr(actual, field) == getattr(expected, field), field
    assert {c.commitment_id: c for c in actual.commitments} == {c.commitment_id: c for c in expected.commitments}
    assert actual.spend == expected.spend
    assert actual == expected
    assert project(estimated, params, Scenario.CONSERVATIVE, 12) == project(reference, params, Scenario.CONSERVATIVE, 12)


@pytest.mark.parametrize("user", PERSONAS)
def test_every_commitment_has_evidence_in_the_ledger(user, ledger_source):
    snapshot = ledger_source.snapshot(user)
    txn_ids = {t.txn_id for t in snapshot.transactions}
    for commitment in ledger_source.load(user).commitments:
        assert commitment.evidence_txn_ids, commitment.commitment_id
        assert set(commitment.evidence_txn_ids) <= txn_ids, commitment.commitment_id


@pytest.mark.parametrize("user", PERSONAS)
def test_commitment_ids_are_unique(user, ledger_source):
    ids = [c.commitment_id for c in ledger_source.load(user).commitments]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("user", PERSONAS)
def test_unexpected_expense_is_not_in_december_and_sets_the_stress_shock(user, ledger_source, params):
    snapshot = ledger_source.snapshot(user)
    shocks = [t for t in snapshot.transactions if -t.amount == UNEXPECTED_EXPENSE and t.kind.value == "purchase"]
    assert len(shocks) == 1
    assert cycle_of(shocks[0].date).month not in params.seasonal_months
    assert ledger_source.load(user).largest_one_off_expense == UNEXPECTED_EXPENSE


@pytest.mark.parametrize("user", PERSONAS)
def test_seeded_conditions_are_flagged(user, ledger_source, params):
    envelope = estimate_model(ledger_source.snapshot(user), params)
    codes = {w.code for w in envelope.warnings}
    assert envelope.ok
    assert {"DUPLICATE_TXN_ID", "NEAR_DUPLICATE"} <= codes
    assert envelope.data.spend.seasonal_factors == {12: Fraction(49, 30)}


def test_ledger_ends_the_day_before_the_october_salary(ledger_source):
    snapshot = ledger_source.snapshot("camila")
    assert snapshot.as_of == date(2026, 10, 29)
    assert {cycle_of(t.date) for t in snapshot.transactions} == {Month(2025, 11).plus(k) for k in range(12)}


@pytest.mark.parametrize("user", PERSONAS)
def test_generated_ledgers_are_deterministic_and_committed(user):
    committed = (LEDGERS / f"{user}.json").read_text(encoding="utf-8")
    assert render(user) == committed, "regenerate with: make ledgers"
    assert json.loads(committed)["user_id"] == user
