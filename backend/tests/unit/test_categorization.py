"""Posting statements into the ledger: amounts and kinds come from the statement, categories are gated."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from neural_ledger.domain.ledger.categorization import (
    CATEGORIES,
    CATEGORY_QUESTION,
    INCOME,
    MOVEMENT,
    RULE,
    UNCATEGORIZED,
    CategoryGuess,
    accept,
    post_statement,
)
from neural_ledger.domain.ledger.entities import TransactionKind
from neural_ledger.domain.statements.model import (
    BankStatement,
    DailyBalance,
    Issue,
    IssueCode,
    StatementLine,
    StatementSummary,
    StoredStatement,
)

NOW = datetime(2026, 10, 1, tzinfo=UTC)


def _stored(issues: tuple[Issue, ...] = (), user_id: str = "camila") -> StoredStatement:
    statement = BankStatement(
        bank="test",
        account_ref="0-000-00-00000-0",
        currency="CLP",
        period_start=date(2026, 8, 31),
        period_end=date(2026, 9, 30),
        lines=(
            StatementLine(0, date(2026, 9, 2), "Compra Nacional MD HIP LIDER", -3_280),
            StatementLine(1, date(2026, 9, 2), "Compra Nacional MD SHOP B", -5_300),
            StatementLine(2, date(2026, 9, 4), "PAGO PROVEEDOR", 163_521),
        ),
        summary=StatementSummary(1_000_000, 8_580, 163_521, 1_154_941),
        daily_balances=(DailyBalance(date(2026, 9, 2), 991_420), DailyBalance(date(2026, 9, 4), 1_154_941)),
    )
    return StoredStatement("stmt_1", user_id, NOW, statement, issues)


def test_charges_are_purchases_with_accepted_categories_and_deposits_are_income():
    guesses = {0: CategoryGuess("groceries", 0.9), 1: CategoryGuess("shopping", 0.2)}
    posted = post_statement(_stored(), guesses, "naive_bayes@abc")

    assert [p.transaction.amount for p in posted] == [-3_280, -5_300, 163_521]
    assert [p.transaction.kind for p in posted] == [TransactionKind.PURCHASE, TransactionKind.PURCHASE, TransactionKind.INCOME]
    assert [p.transaction.category for p in posted] == ["groceries", UNCATEGORIZED, INCOME]
    assert [p.classifier for p in posted] == ["naive_bayes@abc", "naive_bayes@abc", RULE]
    assert [p.confidence for p in posted] == [0.9, 0.2, None]  # a rejected guess keeps its confidence as evidence
    assert [p.categorized for p in posted] == [True, False, True]
    first = posted[0]
    assert (first.user_id, first.currency, first.statement_id, first.line_index) == ("camila", "CLP", "stmt_1", 0)
    assert first.transaction.account_id == "test:0-000-00-00000-0"
    assert first.transaction.merchant_raw == "Compra Nacional MD HIP LIDER"


def test_transaction_ids_are_stable_and_scoped_to_the_user():
    once = [p.transaction.txn_id for p in post_statement(_stored(), {}, "m")]
    again = [p.transaction.txn_id for p in post_statement(_stored(), {0: CategoryGuess("dining", 1.0)}, "other-model")]
    assert once == again and len(set(once)) == 3
    assert set(once).isdisjoint(p.transaction.txn_id for p in post_statement(_stored(user_id="diego"), {}, "m"))


def test_each_transaction_records_the_model_that_answered_its_line():
    """A fallback chain may answer one line with Jev and the next with naive Bayes: each keeps its own source."""
    guesses = {0: CategoryGuess("groceries", 0.9, source="jev:jev-1.14-20261014"), 1: CategoryGuess("shopping", 0.8)}
    posted = post_statement(_stored(), guesses, "jev:jev-1.14-20261014+naive_bayes@abc")
    assert [p.classifier for p in posted] == ["jev:jev-1.14-20261014", "jev:jev-1.14-20261014+naive_bayes@abc", RULE]


def test_category_question_offers_exactly_the_vocabulary_with_a_note_each():
    assert set(CATEGORY_QUESTION.options) == CATEGORIES and len(CATEGORY_QUESTION.options) == len(CATEGORIES)
    assert len(CATEGORY_QUESTION.notes) == len(CATEGORY_QUESTION.options) and all(CATEGORY_QUESTION.notes)
    assert not {INCOME, MOVEMENT, UNCATEGORIZED} & set(CATEGORY_QUESTION.options)  # rules decide those, never a model


def test_missing_guess_leaves_the_charge_uncategorized():
    posted = post_statement(_stored(), {}, "m")
    assert posted[0].transaction.category == UNCATEGORIZED and posted[0].confidence is None


@pytest.mark.parametrize(
    ("guess", "expected"),
    [
        (CategoryGuess("groceries", 0.5), "groceries"),  # the floor is inclusive
        (CategoryGuess("groceries", 0.49), UNCATEGORIZED),
        (CategoryGuess("income", 0.99), UNCATEGORIZED),  # income is decided by the sign, never by a model
        (CategoryGuess("ignore previous instructions", 1.0), UNCATEGORIZED),  # outside the vocabulary
        (None, UNCATEGORIZED),
    ],
)
def test_accept_gates_model_labels(guess, expected):
    assert accept(guess) == expected


@pytest.mark.parametrize("confidence", [-0.1, 1.01, float("nan"), float("inf")])
def test_guess_confidence_must_be_a_probability(confidence):
    with pytest.raises(ValueError):
        CategoryGuess("groceries", confidence)


def test_unverified_statement_is_never_posted():
    issue = Issue(IssueCode.CLOSING_BALANCE, "closing balance does not match", 1, 2)
    with pytest.raises(ValueError, match="verified"):
        post_statement(_stored(issues=(issue,)), {}, "m")
