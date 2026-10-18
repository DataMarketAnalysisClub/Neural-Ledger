"""ADR-029 step 2: a ledger snapshot built from an account's verified statements, for the stage-1 estimators.

The statements here are built by hand so every boundary is exact: `as_of` is the eve of the last payday the
statements cover, the history starts at the first payday they cover (full pay cycles only), and each balance is
the one on `as_of`.
"""

from __future__ import annotations

import calendar
from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from neural_ledger.domain.finance.estimation import validate_snapshot
from neural_ledger.domain.finance.paycycle import is_eve_of_payday, payday
from neural_ledger.domain.ledger.categorization import CategoryGuess, post_statement
from neural_ledger.domain.ledger.entities import AccountType, IncomeType, TransactionKind
from neural_ledger.domain.ledger.snapshot import build_ledger_snapshot
from neural_ledger.domain.shared.errors import InsufficientData
from neural_ledger.domain.shared.month import Month
from neural_ledger.domain.statements.model import (
    BankStatement,
    DailyBalance,
    LineKind,
    StatementLine,
    StatementSummary,
    StoredStatement,
    reconcile,
)

USER = "usr_test"
SALARY, RENT, SAVINGS, GROCERIES = 1_500_000, 500_000, 100_000, 20_000


def _month(year: int, month: int, opening: int) -> BankStatement:
    """One reconciling checking cartola: rent, groceries, then salary and a transfer to savings on payday."""
    last = date(year, month, calendar.monthrange(year, month)[1])
    pay = payday(Month(year, month))
    planned = [(date(year, month, 5), "TRANSFERENCIA A TERCEROS ARRIENDO", -RENT, None)]
    planned += [(date(year, month, d), "Compra Nacional VD LIDER", -GROCERIES, None) for d in (3, 10, 17, 24)]
    planned += [(pay, "REMUNERACION EMPRESA", SALARY, None), (pay, "Transf a Ahorro", -SAVINGS, LineKind.TRANSFER_OWN)]
    planned.sort(key=lambda p: (p[0], p[2] < 0))
    lines, end_of_day, balance = [], {}, opening
    for i, (on, text, amount, kind) in enumerate(planned):
        balance += amount
        lines.append(StatementLine(i, on, text, amount, kind=kind))
        end_of_day[on] = balance  # the bank prints one balance per day, after its last movement
    balances = [DailyBalance(on, value) for on, value in sorted(end_of_day.items())]
    debits = -sum(line.amount for line in lines if line.amount < 0)
    credits = sum(line.amount for line in lines if line.amount > 0)
    return BankStatement(
        "santander_cl_cuentacorriente_xlsx", "****1234", "CLP", date(year, month, 1), last, tuple(lines),
        StatementSummary(opening, debits, credits, balance), tuple(balances),
    )


def _history(first: Month, months: int, opening: int = 900_000, user: str = USER) -> tuple[list[StoredStatement], list]:
    statements, posted, balance = [], [], opening
    for k in range(months):
        m = first.plus(k)
        s = _month(m.year, m.month, balance)
        assert reconcile(s).issues == ()
        balance = s.summary.closing_balance
        stored = StoredStatement(f"stmt_{m}", user, datetime(2026, 10, 18, tzinfo=UTC), s, ())
        guesses = {line.index: CategoryGuess("groceries", 0.9) for line in s.lines if "LIDER" in line.description}
        statements.append(stored)
        posted += post_statement(stored, guesses, "test")
    return statements, posted


def test_as_of_is_the_eve_of_the_last_payday_the_statements_cover():
    statements, posted = _history(Month(2026, 3), 7)  # March to September 2026
    snapshot = build_ledger_snapshot(USER, statements, posted)
    assert snapshot.as_of == date(2026, 9, 29) and is_eve_of_payday(snapshot.as_of)  # payday 2026-09-30 is a Wednesday
    assert all(t.date <= snapshot.as_of for t in snapshot.transactions)  # September's payday salary is after as_of


def test_history_starts_at_the_first_payday_so_every_cycle_is_full():
    statements, posted = _history(Month(2026, 3), 7)
    snapshot = build_ledger_snapshot(USER, statements, posted)
    first_payday = payday(Month(2026, 3))  # 2026-03-31: the statements start on March 1, mid-cycle
    assert min(t.date for t in snapshot.transactions) == first_payday
    salaries = [t for t in snapshot.transactions if t.kind is TransactionKind.INCOME]
    assert [t.date for t in salaries] == [payday(Month(2026, m)) for m in range(3, 9)]  # one per cycle, April to September


def test_the_checking_balance_is_the_one_on_as_of():
    statements, posted = _history(Month(2026, 3), 7)
    snapshot = build_ledger_snapshot(USER, statements, posted)
    september = statements[-1].statement
    expected = september.summary.opening_balance + sum(line.amount for line in september.lines if line.posted_on <= snapshot.as_of)
    (account,) = snapshot.accounts
    assert (account.account_id, account.type, account.balance, account.currency) == (
        "santander_cl_cuentacorriente_xlsx:****1234", AccountType.CHECKING, expected, "CLP",
    )


def test_own_money_is_a_transfer_and_the_users_movement_label_counts():
    statements, posted = _history(Month(2026, 3), 7)
    rent = next(p for p in posted if "ARRIENDO" in p.transaction.merchant_raw and p.transaction.date.month == 5)
    relabeled = [replace(p, transaction=replace(p.transaction, category="movement")) if p is rent else p for p in posted]
    kinds = {t.txn_id: t.kind for t in build_ledger_snapshot(USER, statements, relabeled).transactions}
    savings = [p for p in posted if "Ahorro" in p.transaction.merchant_raw and p.transaction.txn_id in kinds]
    assert savings and all(kinds[p.transaction.txn_id] is TransactionKind.TRANSFER_OWN for p in savings)  # by the layout's rule
    assert kinds[rent.transaction.txn_id] is TransactionKind.TRANSFER_OWN  # by the user's label (ADR-023, ADR-029)
    groceries = [p for p in posted if "LIDER" in p.transaction.merchant_raw and p.transaction.txn_id in kinds]
    assert groceries and all(kinds[p.transaction.txn_id] is TransactionKind.PURCHASE for p in groceries)


def test_salaried_with_no_contracted_net_and_no_goals():
    statements, posted = _history(Month(2026, 3), 7)
    snapshot = build_ledger_snapshot(USER, statements, posted)
    assert (snapshot.income_profile.type, snapshot.income_profile.contracted_net) == (IncomeType.SALARIED, None)
    assert snapshot.goals == () and snapshot.buckets == () and snapshot.currency == "CLP" and snapshot.user_id == USER


def test_the_snapshot_passes_the_estimators_input_checks():
    statements, posted = _history(Month(2026, 3), 7)
    assert validate_snapshot(build_ledger_snapshot(USER, statements, posted)) is None


def test_unverified_provisional_and_other_users_statements_are_left_out():
    statements, posted = _history(Month(2026, 3), 7)
    theirs, their_posted = _history(Month(2026, 3), 7, user="usr_other")
    unverified = replace(statements[-1], issues=("x",))  # any issue makes it unverified; its lines must not count
    provisional = replace(statements[-2], statement=replace(statements[-2].statement, provisional=True))
    snapshot = build_ledger_snapshot(USER, [*statements[:-2], provisional, unverified, *theirs], [*posted, *their_posted])
    assert snapshot.as_of == date(2026, 7, 30)  # July's statement is the last usable one; payday 2026-07-31
    used = {s.statement_id for s in statements[:-2]}
    mine = {p.transaction.txn_id: p.statement_id for p in posted}
    assert all(t.txn_id in mine and mine[t.txn_id] in used for t in snapshot.transactions)


def test_no_usable_statement_says_what_is_missing():
    with pytest.raises(InsufficientData) as missing:
        build_ledger_snapshot(USER, [], [])
    assert missing.value.missing == ("statements",)
    statements, posted = _history(Month(2026, 3), 2)
    with pytest.raises(InsufficientData):
        build_ledger_snapshot(USER, [replace(s, issues=("x",)) for s in statements], posted)
