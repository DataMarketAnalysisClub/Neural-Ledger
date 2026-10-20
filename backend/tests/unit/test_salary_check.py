"""ADR-049 §1-4: whether the statements support a declared salary, derived on read from declarations and credits.

Paydays used here (last weekday of the month): 2026-07-31 Fri, 2026-08-31 Mon, 2026-09-30 Wed, 2026-10-30 Fri,
2026-11-30 Mon, 2026-12-31 Thu. Payday 2026-10-30 ± 3 business days is 2026-10-27 to 2026-11-04.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from neural_ledger.domain.ledger.entities import AccountType
from neural_ledger.domain.memory.catalog import ChatOrigin, Declaration, SalaryNet, Source
from neural_ledger.domain.memory.salary_check import (
    AccountSpan,
    Credit,
    Outcome,
    Status,
    business_window,
    check_salary,
    eligible_inputs,
)
from neural_ledger.domain.shared.month import Month
from neural_ledger.domain.statements.model import StoredStatement
from tests.unit.test_statement_snapshot import SALARY as SNAPSHOT_SALARY
from tests.unit.test_statement_snapshot import USER, _history

CHECKING = "santander:****1234"
ALL_YEAR = (AccountSpan(CHECKING, date(2026, 1, 1), date(2027, 2, 28)),)
TODAY = date(2027, 1, 20)


def declared(version: int, amount: int, effective_from: str, confirmed: date = date(2026, 7, 1)) -> Declaration:
    return Declaration(
        memory_id=f"mem_{version}", chain_id="chn_1", version=version, user_id="u1",
        value=SalaryNet(amount, Month.parse(effective_from)), confirmed_at=datetime(confirmed.year, confirmed.month, confirmed.day, 12, tzinfo=UTC),
        source=Source.CHAT, origin=ChatOrigin("s_1", f"m_{version}"), audit_ref=f"evt_{version}",
    )


def credit(day: date, amount: int, txn_id: str | None = None) -> Credit:
    return Credit("st_1", txn_id or f"tx_{day.isoformat()}_{amount}", amount, day)


def salaries(amount: int, *paydays: date) -> list[Credit]:
    return [credit(day, amount) for day in paydays]


def outcomes(check) -> dict[str, Outcome]:
    return {str(e.pay_month): e.outcome for e in check.evidence}


PAYDAYS = (date(2026, 7, 31), date(2026, 8, 31), date(2026, 9, 30), date(2026, 10, 30), date(2026, 11, 30), date(2026, 12, 31))


def test_salary_credits_on_payday_verify_the_declaration():
    check = check_salary([declared(1, 1_200_000, "2026-07")], salaries(1_200_000, *PAYDAYS), ALL_YEAR, TODAY)
    assert check.status is Status.VERIFIED and check.matched == 6 and check.missed == 0
    assert check.matched_amounts(1) == (1_200_000,) * 6
    assert str(check.evidence[-1].pay_month) == "2027-01" and check.evidence[-1].outcome is Outcome.NOT_ELIGIBLE  # not ended


def test_the_date_window_is_three_business_days_either_side():
    assert business_window(date(2026, 10, 30), 3) == (date(2026, 10, 27), date(2026, 11, 4))


@pytest.mark.parametrize(
    ("day", "matched"),
    [(date(2026, 10, 26), False), (date(2026, 10, 27), True), (date(2026, 11, 2), True), (date(2026, 11, 4), True), (date(2026, 11, 5), False)],
)
def test_the_window_edges_are_inclusive_and_cross_months(day, matched):
    check = check_salary([declared(1, 1_200_000, "2026-10")], [credit(day, 1_200_000)], ALL_YEAR, date(2026, 11, 20))
    evidence = check.evidence[0]
    assert str(evidence.pay_month) == "2026-10"  # a credit on 2026-11-02 is October's salary, by its expected payday
    assert (evidence.outcome is Outcome.MATCHED) is matched


@pytest.mark.parametrize(
    ("amount", "matched"),
    [(1_140_000, True), (1_139_999, False), (1_260_000, True), (1_260_001, False)],
)
def test_the_tolerance_is_five_percent_inclusive(amount, matched):
    check = check_salary([declared(1, 1_200_000, "2026-10")], [credit(date(2026, 10, 30), amount)], ALL_YEAR, date(2026, 11, 20))
    assert (check.evidence[0].outcome is Outcome.MATCHED) is matched


def test_ties_go_to_the_smallest_difference_then_the_earliest_date_then_the_txn_id():
    october = [
        credit(date(2026, 10, 29), 1_190_000, "tx_b"),
        credit(date(2026, 10, 30), 1_210_000, "tx_a"),
        credit(date(2026, 10, 30), 1_195_000, "tx_d"),
        credit(date(2026, 10, 30), 1_205_000, "tx_c"),
    ]
    for credits in (october, list(reversed(october))):
        check = check_salary([declared(1, 1_200_000, "2026-10")], credits, ALL_YEAR, date(2026, 11, 20))
        assert check.evidence[0].credit.txn_id == "tx_c"  # 5,000 off, same date as tx_d, lower txn_id
    nearest = [credit(date(2026, 10, 30), 1_000_000, "tx_far"), credit(date(2026, 10, 28), 1_201_000, "tx_near")]
    assert check_salary([declared(1, 1_200_000, "2026-10")], nearest, ALL_YEAR, date(2026, 11, 20)).evidence[0].credit.txn_id == "tx_near"


def test_a_reimport_changes_nothing():
    credits = salaries(1_200_000, *PAYDAYS)
    once = check_salary([declared(1, 1_200_000, "2026-07")], credits, ALL_YEAR, TODAY)
    twice = check_salary([declared(1, 1_200_000, "2026-07")], credits + credits, ALL_YEAR + ALL_YEAR, TODAY)
    assert once == twice


def test_a_missing_statement_is_never_a_non_compliance():
    gap = (AccountSpan(CHECKING, date(2026, 1, 1), date(2026, 9, 25)), AccountSpan(CHECKING, date(2026, 10, 6), date(2027, 2, 28)))
    check = check_salary([declared(1, 1_200_000, "2026-07")], salaries(1_200_000, *PAYDAYS[:2], *PAYDAYS[3:]), gap, TODAY)
    assert outcomes(check)["2026-09"] is Outcome.NOT_ELIGIBLE
    assert check.missed == 0 and check.status is Status.VERIFIED


def test_a_statement_gap_breaks_consecutiveness():
    gap = (AccountSpan(CHECKING, date(2026, 1, 1), date(2026, 9, 25)), AccountSpan(CHECKING, date(2026, 10, 6), date(2027, 2, 28)))
    check = check_salary([declared(1, 1_200_000, "2026-07")], salaries(1_200_000, PAYDAYS[0], PAYDAYS[4], PAYDAYS[5]), gap, TODAY)
    assert [outcomes(check)[m] for m in ("2026-08", "2026-09", "2026-10")] == [Outcome.MISSED, Outcome.NOT_ELIGIBLE, Outcome.MISSED]
    assert check.status is Status.VERIFIED  # miss, gap, miss: never two in a row


def test_every_account_must_cover_the_window_whole():
    savings = AccountSpan("santander:****9999", date(2026, 1, 1), date(2027, 2, 28))
    checking = (AccountSpan(CHECKING, date(2026, 1, 1), date(2026, 10, 28)), AccountSpan(CHECKING, date(2026, 11, 2), date(2027, 2, 28)))
    check = check_salary([declared(1, 1_200_000, "2026-10")], [], (savings, *checking), date(2026, 11, 20))
    assert check.evidence[0].outcome is Outcome.NOT_ELIGIBLE  # savings alone is not enough while checking has a hole


@pytest.mark.parametrize(
    "checking",
    [AccountSpan(CHECKING, date(2026, 1, 1), date(2026, 10, 25)), AccountSpan(CHECKING, date(2026, 11, 1), date(2027, 2, 28))],
    ids=["stops before", "starts after"],
)
def test_an_account_that_stops_or_starts_leaves_the_payday_not_eligible(checking):
    """The salary may be paid into it: nothing tells a closed account from a statement not imported (ADR-049 §2)."""
    savings = AccountSpan("santander:****9999", date(2026, 1, 1), date(2027, 2, 28))
    check = check_salary([declared(1, 1_200_000, "2026-10")], [], (savings, checking), date(2026, 11, 20))
    assert check.evidence[0].outcome is Outcome.NOT_ELIGIBLE


def test_two_consecutive_misses_are_a_conflict_that_a_later_match_does_not_clear():
    check = check_salary([declared(1, 1_200_000, "2026-07")], salaries(1_200_000, *PAYDAYS[:3], PAYDAYS[5]), ALL_YEAR, TODAY)
    assert [outcomes(check)[m] for m in ("2026-10", "2026-11", "2026-12")] == [Outcome.MISSED, Outcome.MISSED, Outcome.MATCHED]
    assert check.status is Status.CONFLICT and check.missed == 2


def test_a_new_confirmation_ends_the_conflict():
    credits = salaries(1_200_000, *PAYDAYS[:3], PAYDAYS[5])
    reconfirmed = [declared(1, 1_200_000, "2026-07"), declared(2, 1_200_000, "2026-07", confirmed=date(2026, 12, 15))]
    check = check_salary(reconfirmed, credits, ALL_YEAR, TODAY)
    assert check.current.version == 2 and check.status is Status.VERIFIED
    assert [outcomes(check)[m] for m in ("2026-10", "2026-11")] == [Outcome.BEFORE_CONFIRMATION] * 2
    assert check.matched == 4  # historical matches still count


def test_misses_before_the_confirmation_do_not_count_but_matches_do():
    late = declared(1, 1_200_000, "2026-07", confirmed=date(2026, 11, 15))
    check = check_salary([late], salaries(1_200_000, PAYDAYS[0], PAYDAYS[4], PAYDAYS[5]), ALL_YEAR, TODAY)
    assert [outcomes(check)[m] for m in ("2026-07", "2026-08", "2026-09", "2026-10")] == [Outcome.MATCHED] + [Outcome.BEFORE_CONFIRMATION] * 3
    assert check.status is Status.VERIFIED and check.missed == 0


def test_one_payday_miss_is_not_a_conflict():
    check = check_salary([declared(1, 1_200_000, "2026-07")], salaries(1_200_000, *PAYDAYS[:4], PAYDAYS[5]), ALL_YEAR, TODAY)
    assert check.status is Status.VERIFIED and check.missed == 1


def test_a_raise_is_checked_against_its_own_amount_from_its_month():
    versions = [declared(1, 1_000_000, "2026-07"), declared(2, 1_200_000, "2026-10", confirmed=date(2026, 10, 19))]
    credits = salaries(1_000_000, *PAYDAYS[:3]) + salaries(1_200_000, *PAYDAYS[3:])
    check = check_salary(versions, credits, ALL_YEAR, TODAY)
    assert check.current.version == 2 and check.matched == 3 and check.status is Status.VERIFIED
    assert check.matched_amounts(1) == (1_000_000,) * 3 and check.matched_amounts(2) == (1_200_000,) * 3


def test_a_credit_that_fits_both_versions_is_a_match_of_the_current_one():
    versions = [declared(1, 1_150_000, "2026-07"), declared(2, 1_200_000, "2026-10", confirmed=date(2026, 10, 19))]
    check = check_salary(versions, salaries(1_170_000, *PAYDAYS), ALL_YEAR, TODAY)
    assert all(e.outcome is Outcome.MATCHED for e in check.evidence if e.version == 2 and str(e.pay_month) < "2027-01")
    assert check.status is Status.VERIFIED and check.missed == 0


def test_a_raise_not_paid_yet_is_declared_and_a_future_one_leaves_the_present_alone():
    raise_ = [declared(1, 1_000_000, "2026-07"), declared(2, 1_200_000, "2026-12", confirmed=date(2026, 12, 1))]
    check = check_salary(raise_, salaries(1_000_000, *PAYDAYS[:5]), ALL_YEAR, date(2026, 12, 20))
    assert check.current.version == 2 and check.status is Status.DECLARED and check.matched == 0
    future = [declared(1, 1_000_000, "2026-07"), declared(2, 1_200_000, "2027-03", confirmed=date(2026, 12, 1))]
    check = check_salary(future, salaries(1_000_000, *PAYDAYS[:5]), ALL_YEAR, date(2026, 12, 20))
    assert check.current.version == 1 and check.status is Status.VERIFIED and check.matched == 5


def test_a_declaration_that_starts_later_has_no_evidence_yet():
    check = check_salary([declared(1, 1_200_000, "2027-03")], salaries(1_200_000, *PAYDAYS), ALL_YEAR, TODAY)
    assert check.current is None and check.evidence == () and check.status is Status.DECLARED


def test_no_statements_means_nothing_is_eligible():
    check = check_salary([declared(1, 1_200_000, "2026-07")], [], (), TODAY)
    assert {e.outcome for e in check.evidence} == {Outcome.NOT_ELIGIBLE} and check.status is Status.DECLARED


def test_only_the_users_verified_final_cycle_account_income_is_eligible():
    statements, posted = _history(Month(2026, 3), 3)
    other_statements, other_posted = _history(Month(2026, 3), 1, user="someone_else")
    unverified = replace(statements[2], issues=(object(),))  # reconciliation found a problem
    card = replace(statements[1], statement=replace(statements[1].statement, account_type=AccountType.CREDIT_CARD))
    provisional = StoredStatement("stmt_prov", USER, statements[0].imported_at, replace(statements[0].statement, provisional=True), ())
    never_posted = [replace(p, statement_id="stmt_prov") for p in posted[:3]]  # defence in depth: never posted anyway
    credits, spans = eligible_inputs(USER, [statements[0], card, unverified, provisional, *other_statements], posted + other_posted + never_posted)
    assert {c.statement_id for c in credits} == {statements[0].statement_id}
    assert [c.amount for c in credits] == [SNAPSHOT_SALARY]  # the transfer to savings is not income
    assert [s.start for s in spans] == [date(2026, 3, 1)]
