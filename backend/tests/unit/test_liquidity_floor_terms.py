"""ADR-037: the user's liquidity floor is an action like a savings rule, with its own route and limit."""

from __future__ import annotations

from datetime import date

import pytest

from neural_ledger.domain.actions.terms import (
    ActionTerms,
    ActionType,
    Frequency,
    SavingsRule,
    liquidity_floor_from,
    savings_rules,
    terms_for_floor,
)
from neural_ledger.domain.agent.questions import INTENT_QUESTION, Intent
from neural_ledger.domain.permissions.policy import PP_0_1, check_terms
from neural_ledger.domain.shared.errors import InvalidInput
from neural_ledger.domain.shared.month import Month


def _rule(rule_id: str, amount: int, action: ActionType) -> SavingsRule:
    return SavingsRule(rule_id, "u", amount, "CLP", Frequency.MONTHLY, "checking", "checking", date(2026, 10, 1), "auth", action)


def test_floor_terms_move_nothing_and_start_on_the_first_projected_cycle():
    terms = terms_for_floor(100_000, "CLP", Month(2026, 10))
    assert (terms.action, terms.amount, terms.source_account, terms.destination) == (ActionType.SET_LIQUIDITY_FLOOR, 100_000, "checking", "checking")
    assert terms.effective_date == date(2026, 10, 1) and terms.frequency is Frequency.MONTHLY
    assert check_terms(terms, PP_0_1).allowed


def test_a_floor_must_be_positive():
    with pytest.raises(InvalidInput):
        terms_for_floor(0, "CLP", Month(2026, 10))


def test_each_action_keeps_its_own_route():
    savings_to_checking = ActionTerms(ActionType.CREATE_SAVINGS_RULE, 50_000, "CLP", Frequency.MONTHLY, "checking", "checking", date(2026, 10, 1))
    floor_to_savings = ActionTerms(ActionType.SET_LIQUIDITY_FLOOR, 50_000, "CLP", Frequency.MONTHLY, "checking", "sandbox_savings", date(2026, 10, 1))
    for terms in (savings_to_checking, floor_to_savings):
        decision = check_terms(terms, PP_0_1)
        assert not decision.allowed and decision.reason.value == "UNKNOWN_DESTINATION" and decision.tier.value == "T3"


def test_a_floor_has_its_own_limit_not_the_transfer_limit():
    assert check_terms(terms_for_floor(2_000_000, "CLP", Month(2026, 10)), PP_0_1).allowed  # above the 1,000,000 per transfer
    over = check_terms(terms_for_floor(PP_0_1.max_liquidity_floor + 1, "CLP", Month(2026, 10)), PP_0_1)
    assert not over.allowed and over.reason.value == "AMOUNT_OVER_LIMIT"


def test_the_latest_floor_rule_wins_and_never_counts_as_a_transfer():
    rules = (
        _rule("r1", 200_000, ActionType.SET_LIQUIDITY_FLOOR),
        _rule("r2", 30_000, ActionType.CREATE_SAVINGS_RULE),
        _rule("r3", 100_000, ActionType.SET_LIQUIDITY_FLOOR),
    )
    assert liquidity_floor_from(rules) == 100_000
    assert [r.rule_id for r in savings_rules(rules)] == ["r2"]
    assert liquidity_floor_from(()) is None


def test_the_intent_question_offers_the_floor_with_a_note():
    assert Intent.SET_LIQUIDITY_FLOOR.value in INTENT_QUESTION.options
    assert len(INTENT_QUESTION.notes) == len(INTENT_QUESTION.options)
