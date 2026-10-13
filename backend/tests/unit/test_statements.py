"""Statement reconciliation: every misread the reader can make must break an equality."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

from neural_ledger.domain.statements.model import (
    BankStatement,
    DailyBalance,
    IssueCode,
    StatementLine,
    StatementSummary,
    reconcile,
)


def _statement(**changes) -> BankStatement:
    lines = (
        StatementLine(0, date(2026, 9, 2), "Compra Nacional MD SHOP A", -3_280),
        StatementLine(1, date(2026, 9, 2), "Compra Nacional MD SHOP B", -5_300),
        StatementLine(2, date(2026, 9, 4), "PAGO PROVEEDOR", 163_521),
        StatementLine(3, date(2026, 9, 30), "Transf a Ahorro", -200_000),
    )
    base = BankStatement(
        bank="test",
        account_ref="0-000-00-00000-0",
        currency="CLP",
        period_start=date(2026, 8, 31),
        period_end=date(2026, 9, 30),
        lines=lines,
        summary=StatementSummary(opening_balance=1_000_000, total_debits=208_580, total_credits=163_521, closing_balance=954_941),
        daily_balances=(
            DailyBalance(date(2026, 9, 2), 991_420),
            DailyBalance(date(2026, 9, 4), 1_154_941),
            DailyBalance(date(2026, 9, 30), 954_941),
        ),
    )
    return replace(base, **changes)


def _codes(statement: BankStatement, **kwargs) -> list[IssueCode]:
    return [issue.code for issue in reconcile(statement, **kwargs).issues]


def test_consistent_statement_reconciles():
    assert reconcile(_statement()).ok


def test_misread_amount_breaks_totals_and_daily_balance():
    s = _statement()
    misread = replace(s.lines[1], amount=-5_800)
    codes = _codes(replace(s, lines=(s.lines[0], misread, *s.lines[2:])))
    assert IssueCode.TOTAL_DEBITS in codes
    assert codes.count(IssueCode.DAILY_BALANCE) == 1  # resyncs after the bad day instead of cascading


def test_dropped_line_is_detected():
    s = _statement()
    assert IssueCode.TOTAL_CREDITS in _codes(replace(s, lines=(s.lines[0], s.lines[1], s.lines[3])))


def test_line_moved_to_another_day_breaks_daily_balance_only():
    s = _statement()
    moved = replace(s.lines[2], posted_on=date(2026, 9, 2))
    # Totals still match; only the two days it moved between disagree with the printed balances.
    issues = reconcile(replace(s, lines=(s.lines[0], s.lines[1], moved, s.lines[3]))).issues
    assert [(i.code, i.on) for i in issues] == [(IssueCode.DAILY_BALANCE, date(2026, 9, 2)), (IssueCode.DAILY_BALANCE, date(2026, 9, 4))]


def test_charge_read_as_deposit_is_detected():
    s = _statement()
    flipped = replace(s.lines[0], amount=3_280)
    codes = _codes(replace(s, lines=(flipped, *s.lines[1:])))
    assert {IssueCode.TOTAL_DEBITS, IssueCode.TOTAL_CREDITS} <= set(codes)


def test_inconsistent_printed_totals_are_detected():
    s = _statement()
    assert IssueCode.CLOSING_BALANCE in _codes(replace(s, summary=replace(s.summary, closing_balance=954_940)))


def test_out_of_period_line():
    s = _statement()
    late = replace(s.lines[3], posted_on=date(2026, 10, 1))
    assert IssueCode.OUT_OF_PERIOD in _codes(replace(s, lines=(*s.lines[:3], late)))


def test_without_summary_nothing_can_be_verified():
    assert _codes(_statement(summary=None)) == [IssueCode.NO_SUMMARY]


def test_low_confidence_is_flagged_even_when_totals_match():
    s = _statement()
    shaky = replace(s.lines[0], confidence=0.41)
    statement = replace(s, lines=(shaky, *s.lines[1:]))
    assert reconcile(statement).ok
    assert _codes(statement, min_confidence=0.6) == [IssueCode.LOW_CONFIDENCE]
