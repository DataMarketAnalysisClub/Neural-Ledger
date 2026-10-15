"""Card statements in the domain: partial printed totals, cuota schedules, and posting by line kind."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from neural_ledger.domain.ledger.categorization import MOVEMENT, RULE, CategoryGuess, classifiable, post_statement
from neural_ledger.domain.ledger.entities import AccountType, TransactionKind
from neural_ledger.domain.shared.month import Month
from neural_ledger.domain.statements.model import (
    BankStatement,
    CardObligations,
    Installment,
    IssueCode,
    LineKind,
    ScheduledAmount,
    SectionTotal,
    StatementLine,
    StatementSummary,
    StoredStatement,
    installment_plans,
    installment_schedule,
    reconcile,
)

END = date(2026, 8, 27)


def _card(**changes) -> BankStatement:
    lines = (
        StatementLine(0, date(2026, 7, 31), "MONTO CANCELADO", 100_000, kind=LineKind.PAYMENT, section="B"),
        StatementLine(1, date(2026, 8, 3), "SHOP ONE", -10_000, kind=LineKind.PURCHASE, section="D"),
        StatementLine(2, END, "STORE", -10_000, kind=LineKind.PURCHASE, section="E", installment=Installment(2, 3, 30_000, Decimal(0), date(2026, 6, 15))),
        StatementLine(3, END, "GADGET", -17_633, kind=LineKind.PURCHASE, section="E", installment=Installment(1, 3, 52_900, Decimal(0), date(2026, 8, 14))),
        StatementLine(4, date(2026, 8, 10), "SHOP ONE REVERSA", 4_850, kind=LineKind.REFUND, section="G"),
        StatementLine(5, END, "COMISION ADMINISTRACION MENSUAL", -4_904, kind=LineKind.FEE, section="G"),
    )
    base = BankStatement(
        bank="test_card",
        account_ref="****4321",
        currency="CLP",
        period_start=date(2026, 7, 30),
        period_end=END,
        lines=lines,
        summary=StatementSummary(-100_000, None, None, -37_687),
        account_type=AccountType.CREDIT_CARD,
        section_totals=(SectionTotal("B", 100_000), SectionTotal("D", -10_000), SectionTotal("E", -27_633), SectionTotal("G", -54)),
        obligations=CardObligations(37_687, 5_000, date(2026, 9, 15), upcoming=(ScheduledAmount(Month(2026, 9), 27_633), ScheduledAmount(Month(2026, 10), 17_634))),
    )
    return replace(base, **changes)


def test_a_consistent_card_statement_reconciles():
    assert reconcile(_card()).ok


def test_without_printed_debits_and_credits_the_lines_must_lead_to_the_closing_debt():
    statement = _card(summary=StatementSummary(-100_000, None, None, -37_000))
    (issue,) = reconcile(statement).issues
    assert (issue.code, issue.expected, issue.found) == (IssueCode.CLOSING_BALANCE, -37_000, -37_687)


def test_only_printed_totals_are_checked_and_sections_count_as_printed_totals():
    lines = _card().lines
    only_totals = _card(summary=StatementSummary(None, 42_537, 104_850, None), section_totals=(), obligations=None)
    assert reconcile(only_totals).ok
    nothing = _card(summary=None, section_totals=(), obligations=None)
    assert [i.code for i in reconcile(nothing).issues] == [IssueCode.NO_SUMMARY]
    sections_only = _card(summary=None, obligations=None)
    assert reconcile(sections_only).ok
    moved = replace(lines[1], section="G")
    assert [i.code for i in reconcile(_card(lines=(lines[0], moved, *lines[2:]))).issues] == [IssueCode.SECTION_TOTAL, IssueCode.SECTION_TOTAL]


def test_cuotas_left_follow_the_issuers_rounding_rule():
    store, gadget = installment_plans(_card())
    assert (store.remaining, gadget.remaining) == ((10_000,), (17_633, 17_634))
    assert installment_schedule(_card()) == (ScheduledAmount(Month(2026, 9), 27_633), ScheduledAmount(Month(2026, 10), 17_634))


def test_with_interest_cuotas_are_equal_and_without_a_printed_purchase_there_is_no_plan():
    lines = _card().lines
    with_interest = replace(lines[3], installment=Installment(1, 3, 52_900, Decimal("0.0345"), date(2026, 8, 14)))
    unknown = replace(lines[2], installment=Installment(2, 3))
    plans = installment_plans(_card(lines=(*lines[:2], unknown, with_interest, *lines[4:])))
    assert [(p.description, p.remaining) for p in plans] == [("GADGET", (17_633, 17_633))]


def test_a_printed_schedule_that_disagrees_with_the_cuotas_is_an_issue():
    o = _card().obligations
    statement = _card(obligations=replace(o, upcoming=(ScheduledAmount(Month(2026, 9), 27_633), ScheduledAmount(Month(2026, 10), 17_633))))
    (issue,) = reconcile(statement).issues
    assert (issue.code, issue.expected, issue.found) == (IssueCode.INSTALLMENT_SCHEDULE, 17_633, 17_634)


def _stored(statement: BankStatement) -> StoredStatement:
    return StoredStatement("stmt_card", "camila", datetime(2026, 9, 1, tzinfo=UTC), statement, ())


def test_card_payments_are_movements_by_rule_and_never_income():
    stored = _stored(_card())
    assert [line.index for line in classifiable(stored)] == [1, 2, 3, 4, 5]  # the payment is not the classifier's
    guesses = {i: CategoryGuess("shopping", 0.9) for i in (1, 2, 3, 4, 5)}
    posted = post_statement(stored, guesses, "model@x")
    kinds = [(p.transaction.kind, p.transaction.category, p.classifier) for p in posted]
    assert kinds[0] == (TransactionKind.CARD_PAYMENT, MOVEMENT, RULE)
    assert [k[0] for k in kinds[1:]] == [TransactionKind.PURCHASE] * 3 + [TransactionKind.REFUND, TransactionKind.FEE]
    assert not any(p.transaction.kind is TransactionKind.INCOME for p in posted)


def test_a_cuota_carries_its_plan_into_the_ledger():
    posted = post_statement(_stored(_card()), {}, "model@x")
    plan = posted[2].transaction.installment
    assert (plan.installment_number, plan.installment_total, plan.original_amount, plan.monthly_rate) == (2, 3, 30_000, Decimal(0))
    next_cuota = replace(_card().lines[2], index=0, installment=Installment(3, 3, 30_000, Decimal(0), date(2026, 6, 15)))
    same_plan_next_month = post_statement(_stored(_card(lines=(next_cuota,))), {}, "m")
    assert same_plan_next_month[0].transaction.installment.plan_id == plan.plan_id
    assert posted[1].transaction.installment is None


def test_unbilled_movements_are_never_posted():
    with pytest.raises(ValueError, match="provisional"):
        post_statement(_stored(_card(provisional=True)), {}, "model@x")


def test_a_checking_account_still_goes_by_sign():
    checking = _card(account_type=AccountType.CHECKING)
    kinds = [p.transaction.kind for p in post_statement(_stored(checking), {}, "model@x")]
    assert kinds[0] is TransactionKind.INCOME and kinds[1] is TransactionKind.PURCHASE
