"""Investment snapshots (ADR-044): amounts become integer pesos once, totals and gains are exact, and the facts and
warnings say what the provider reported and nothing more."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from neural_ledger.domain.agent.verification import verify_explanation
from neural_ledger.domain.investments.model import (
    MAX_GOALS,
    STALE_AFTER,
    InvestmentLink,
    ReportedGoal,
    mask_email,
    overview_caveats,
    overview_facts,
    snapshot_from_report,
)
from neural_ledger.domain.shared.errors import InvalidInput

AT = datetime(2026, 10, 29, 15, 0, tzinfo=UTC)


def _snapshot(*goals: ReportedGoal, synthetic: bool = False, at: datetime = AT):
    return snapshot_from_report("usr_1", "fintual", "CLP", at, goals, synthetic=synthetic)


def test_amounts_round_half_up_once_and_totals_are_exact():
    snapshot = _snapshot(
        ReportedGoal("1", "Viaje", Decimal("1264350.5"), Decimal("1200000")),
        ReportedGoal("2", "Casa", Decimal("99.49"), Decimal("100")),
    )
    assert [goal.value for goal in snapshot.goals] == [1_264_351, 99]
    assert (snapshot.total_value, snapshot.total_deposited, snapshot.total_gain) == (1_264_450, 1_200_100, 64_350)
    assert snapshot.goals[1].gain == -1  # a loss is a negative gain, never rounded away


def test_a_goal_without_deposits_hides_the_total_gain_but_keeps_its_own_value():
    snapshot = _snapshot(ReportedGoal("1", "A", Decimal("10"), Decimal("5")), ReportedGoal("2", "B", Decimal("20")))
    assert (snapshot.total_value, snapshot.total_deposited, snapshot.total_gain) == (30, None, None)
    assert [goal.gain for goal in snapshot.goals] == [5, None]
    keys = {fact.key for fact in overview_facts(snapshot)}
    assert "investments.total_gain" not in keys and "investments.goal.1.gain" in keys and "investments.goal.2.gain" not in keys


def test_an_account_with_no_goals_is_valid_and_worth_nothing():
    snapshot = _snapshot()
    assert (snapshot.total_value, snapshot.total_deposited, snapshot.total_gain) == (0, None, None)


@pytest.mark.parametrize(
    "goal, field",
    [
        (ReportedGoal("1", "x", Decimal("-1")), "goals[0].value"),
        (ReportedGoal("1", "x", Decimal("NaN")), "goals[0].value"),
        (ReportedGoal("1", "x", Decimal("Infinity")), "goals[0].value"),
        (ReportedGoal("1", "x", Decimal("1e13")), "goals[0].value"),
        (ReportedGoal("1", "x", 1.5), "goals[0].value"),  # a float is refused: amounts are exact decimals
        (ReportedGoal("1", "x", True), "goals[0].value"),
        (ReportedGoal("1", "x", Decimal("1"), Decimal("-1e13")), "goals[0].deposited"),
        (ReportedGoal("a b", "x", Decimal("1")), "goals[0].goal_id"),
        (ReportedGoal("", "x", Decimal("1")), "goals[0].goal_id"),
        (ReportedGoal(24, "x", Decimal("1")), "goals[0].goal_id"),
        (ReportedGoal("1", 5, Decimal("1")), "goals[0].name"),
    ],
)
def test_reports_outside_the_contract_are_refused(goal, field):
    with pytest.raises(InvalidInput) as error:
        _snapshot(goal)
    assert error.value.field == field


def test_duplicate_ids_too_many_goals_naive_times_and_unknown_providers_are_refused():
    with pytest.raises(InvalidInput) as error:
        _snapshot(ReportedGoal("1", "a", Decimal("1")), ReportedGoal("1", "b", Decimal("2")))
    assert error.value.field == "goals[1].goal_id"
    with pytest.raises(InvalidInput):
        _snapshot(*(ReportedGoal(str(i), "g", Decimal("1")) for i in range(MAX_GOALS + 1)))
    with pytest.raises(InvalidInput):
        _snapshot(at=AT.replace(tzinfo=None))
    with pytest.raises(InvalidInput):
        snapshot_from_report("usr_1", "another", "CLP", AT, ())
    with pytest.raises(InvalidInput):
        snapshot_from_report("usr_1", "fintual", "USD", AT, ())


def test_goal_names_lose_control_characters_and_are_bounded():
    snapshot = _snapshot(ReportedGoal("1", "Viaje‮\n\x00" + "x" * 200, Decimal("1")))
    name = snapshot.goals[0].name
    assert name.startswith("Viaje") and "\n" not in name and "‮" not in name and "\x00" not in name and len(name) == 120


def test_facts_cover_every_number_and_carry_the_currency():
    snapshot = _snapshot(ReportedGoal("101", "Viaje", Decimal("1000"), Decimal("800")))
    facts = {fact.key: (fact.value, fact.unit) for fact in overview_facts(snapshot)}
    assert facts == {
        "investments.goals": (1, "count"),
        "investments.total_value": (1000, "CLP"),
        "investments.total_deposited": (800, "CLP"),
        "investments.total_gain": (200, "CLP"),
        "investments.goal.101.value": (1000, "CLP"),
        "investments.goal.101.deposited": (800, "CLP"),
        "investments.goal.101.gain": (200, "CLP"),
    }


def test_caveats_say_where_the_figures_come_from_whether_they_are_synthetic_and_when_they_are_stale():
    snapshot = _snapshot(ReportedGoal("1", "Viaje", Decimal("1")), synthetic=True)
    assert [c.code for c in overview_caveats(snapshot, AT)] == ["INVESTMENTS_AS_REPORTED", "INVESTMENTS_SYNTHETIC"]
    assert "INVESTMENTS_STALE" not in {c.code for c in overview_caveats(snapshot, AT + STALE_AFTER)}
    later = overview_caveats(snapshot, AT + STALE_AFTER + timedelta(seconds=1))
    assert [c.code for c in later] == ["INVESTMENTS_AS_REPORTED", "INVESTMENTS_SYNTHETIC", "INVESTMENTS_STALE"]
    for caveat in later:
        assert caveat.must_mention, caveat.code
        # Each message satisfies its own caveat and passes the verifier: no figure, no promise, no "safe" money.
        assert verify_explanation(caveat.message, (), (caveat,)).ok, caveat.code


def test_the_link_repr_hides_the_email_and_the_token():
    link = InvestmentLink("usr_1", "fintual", "fintual", "ana@example.invalid", "tok-secret-value", AT)
    assert "tok-secret-value" not in repr(link) and "ana@" not in repr(link)


@pytest.mark.parametrize("email, masked", [("ana@example.invalid", "a***@example.invalid"), ("x@y.z", "x***@y.z"), ("broken", "***")])
def test_the_email_is_shown_masked(email, masked):
    assert mask_email(email) == masked


def test_snapshot_ids_follow_the_content():
    one = _snapshot(ReportedGoal("1", "Viaje", Decimal("1")))
    assert one.snapshot_id == _snapshot(ReportedGoal("1", "Viaje", Decimal("1"))).snapshot_id
    assert one.snapshot_id != _snapshot(ReportedGoal("1", "Viaje", Decimal("2"))).snapshot_id
    assert one.snapshot_id != _snapshot(ReportedGoal("1", "Viaje", Decimal("1")), at=AT + timedelta(minutes=1)).snapshot_id
