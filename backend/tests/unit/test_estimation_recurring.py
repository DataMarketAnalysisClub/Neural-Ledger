"""Recurring items that end, get replaced or change level (Financial Core 4.1; docs/SCOPE.md F14, F15)."""

from __future__ import annotations

from datetime import date

from neural_ledger.domain.finance.model import CommitmentType
from tests.unit.test_estimation_edges import base_transactions, cycles, estimate, txn


def _monthly(merchant: str, amounts: list[int], months, category: str = "rent", day: int = 5):
    return [txn(date(c.year, c.month, day), -a, merchant, category) for c, a in zip(months, amounts)]


def _without_rent(n: int):
    return [t for t in base_transactions(n) if t.category != "rent"]


def _spend_categories(model) -> set[str]:
    return {c.category for c in model.spend.categories}


def _recurring(model, category: str):
    return [c for c in model.commitments if c.commitment_id.startswith(category)]


# ---- replacement ------------------------------------------------------------------------------


def test_rent_that_changes_landlord_mid_window_leaves_no_phantom_rent(params):
    months = cycles(12)
    old = _monthly("LANDLORD A", [400_000] * 6, months[:6])
    new = _monthly("LANDLORD B", [550_000] * 6, months[6:])
    model = estimate(_without_rent(12) + old + new, params).data
    [rent] = _recurring(model, "rent")
    assert (rent.commitment_id, rent.type, rent.amount, rent.first_due, rent.label) == ("rent", CommitmentType.RENT, 550_000, months[6], "LANDLORD B")
    assert "rent" not in _spend_categories(model)  # the old landlord's history is not variable spend


def test_subscription_switch_keeps_one_commitment_and_no_spend(params):
    months = cycles(12)
    old = _monthly("NETFLIX", [9_000] * 5, months[:5], "subscriptions", day=12)
    new = _monthly("DISNEY PLUS", [8_000] * 7, months[5:], "subscriptions", day=14)
    model = estimate(base_transactions(12) + old + new, params).data
    [sub] = _recurring(model, "subscriptions")
    assert (sub.commitment_id, sub.amount, sub.label) == ("subscriptions", 8_000, "DISNEY PLUS")
    assert "subscriptions" not in _spend_categories(model)


def test_ended_item_without_replacement_stays_in_spend(params):
    gym = _monthly("GYM", [30_000] * 6, cycles(8)[:6], "subscriptions", day=12)
    model = estimate(base_transactions(8) + gym, params).data
    assert not _recurring(model, "subscriptions")
    assert "subscriptions" in _spend_categories(model)


def test_recent_replacement_with_two_payments_is_a_provisional_commitment(params):
    months = cycles(11)
    old = _monthly("LANDLORD A", [500_000] * 9, months[:9])
    new = _monthly("LANDLORD B", [550_000] * 2, months[9:])
    envelope = estimate(_without_rent(11) + old + new, params)
    [rent] = _recurring(envelope.data, "rent")
    assert (rent.commitment_id, rent.amount, rent.first_due, rent.label) == ("rent", 550_000, months[9], "LANDLORD B")
    assert "RECURRING_PROVISIONAL" in {w.code for w in envelope.warnings}
    assert "rent" not in _spend_categories(envelope.data)


def test_two_payments_without_an_ended_item_are_not_a_commitment(params):
    months = cycles(8)
    new = _monthly("CLUB", [40_000] * 2, months[6:], "subscriptions", day=12)
    envelope = estimate(base_transactions(8) + new, params)
    assert not _recurring(envelope.data, "subscriptions")
    assert "RECURRING_PROVISIONAL" not in {w.code for w in envelope.warnings}


# ---- level changes ----------------------------------------------------------------------------


def test_rent_increase_with_the_same_landlord_is_still_a_commitment(params):
    months = cycles(12)
    rent = _monthly("LANDLORD", [500_000] * 8 + [535_000] * 4, months)  # +7%
    model = estimate(_without_rent(12) + rent, params).data
    [commitment] = _recurring(model, "rent")
    assert (commitment.amount, commitment.first_due, commitment.confidence) == (535_000, months[0], 1.0)
    assert "rent" not in _spend_categories(model)


def test_more_than_one_level_change_is_not_recurring(params):
    months = cycles(8)
    bills = _monthly("ENEL", [50_000, 54_000, 50_000, 54_000, 50_000, 54_000, 50_000, 54_000], months, "utilities", day=12)
    model = estimate(base_transactions(8) + bills, params).data
    assert not _recurring(model, "utilities")
    assert "utilities" in _spend_categories(model)
