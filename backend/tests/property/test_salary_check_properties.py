"""ADR-049: the salary check depends on what was imported, never on its order, and a missing statement never counts
against the user."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from neural_ledger.domain.finance.paycycle import payday
from neural_ledger.domain.memory.catalog import ChatOrigin, Declaration, SalaryNet, Source
from neural_ledger.domain.memory.salary_check import AccountSpan, Credit, Outcome, check_salary
from neural_ledger.domain.shared.month import Month

from .strategies import PROPERTY_SETTINGS

pytestmark = pytest.mark.property

FIRST = Month(2026, 1)
TODAY = date(2027, 1, 20)
ACCOUNTS = ("santander:****1234", "bci:****5678")


def _declaration(version: int, amount: int, effective_from: Month, confirmed: date) -> Declaration:
    return Declaration(
        f"mem_{version}", "chn_1", version, "u1", SalaryNet(amount, effective_from),
        datetime(confirmed.year, confirmed.month, confirmed.day, tzinfo=UTC), Source.PROFILE, ChatOrigin("s", f"m{version}"), f"e{version}",
    )


@st.composite
def cases(draw):
    base = draw(st.integers(min_value=500_000, max_value=3_000_000))
    versions = [_declaration(1, base, FIRST, date(2026, 1, 1))]
    if draw(st.booleans()):
        raised = draw(st.integers(min_value=1, max_value=12))
        versions.append(_declaration(2, base + draw(st.integers(0, 400_000)), FIRST.plus(raised), date(2026, 1, 1) + timedelta(days=30 * raised)))
    credits = []
    for k in range(12):
        expected = payday(FIRST.plus(k))
        for j in range(draw(st.integers(0, 3))):
            shift = draw(st.integers(-6, 6))
            amount = draw(st.one_of(st.just(base), st.integers(min_value=1, max_value=4_000_000)))
            credits.append(Credit(f"st_{k}", f"tx_{k}_{j}_{draw(st.integers(0, 9))}", amount, expected + timedelta(days=shift)))
    spans = []
    for account in draw(st.lists(st.sampled_from(ACCOUNTS), min_size=1, max_size=2, unique=True)):
        for k in range(13):
            if draw(st.integers(0, 9)):  # one month in ten is missing
                m = FIRST.plus(k)
                spans.append(AccountSpan(account, m.first_day(), m.plus(1).first_day() - timedelta(days=1)))
    return versions, credits, spans


@PROPERTY_SETTINGS
@given(case=cases(), seed=st.randoms(use_true_random=False))
def test_input_order_and_reimports_do_not_change_the_result(case, seed):
    versions, credits, spans = case
    expected = check_salary(versions, credits, spans, TODAY)
    shuffled = credits + credits[: len(credits) // 2]
    seed.shuffle(shuffled)
    reordered_spans = list(spans)
    seed.shuffle(reordered_spans)
    assert check_salary(list(reversed(versions)), shuffled, reordered_spans, TODAY) == expected


@PROPERTY_SETTINGS
@given(case=cases())
def test_a_transaction_matches_at_most_one_payday(case):
    check = check_salary(*case, TODAY)
    matched = [e.credit.txn_id for e in check.evidence if e.credit is not None]
    assert len(matched) == len(set(matched))


@PROPERTY_SETTINGS
@given(case=cases(), dropped=st.integers(min_value=0, max_value=25))
def test_removing_a_statement_never_creates_a_missed_payday(case, dropped):
    versions, credits, spans = case
    if dropped >= len(spans) or sum(s.account == spans[dropped].account for s in spans) < 2:
        return  # removing an account's only statement removes the account: that is not a missing statement
    full = {e.pay_month: e.outcome for e in check_salary(versions, credits, spans, TODAY).evidence}
    fewer = spans[:dropped] + spans[dropped + 1 :]
    for item in check_salary(versions, credits, fewer, TODAY).evidence:
        if item.outcome is Outcome.MISSED:
            assert full[item.pay_month] is Outcome.MISSED


@PROPERTY_SETTINGS
@given(case=cases(), account=st.sampled_from(ACCOUNTS), cut=st.integers(min_value=1, max_value=12))
def test_an_account_that_stops_early_never_creates_a_missed_payday(case, account, cut):
    """The case a looser rule gets wrong: the salary account's last statements missing looks like a closed account."""
    versions, credits, spans = case
    full = {e.pay_month: e.outcome for e in check_salary(versions, credits, spans, TODAY).evidence}
    stopped = [s for s in spans if s.account != account or s.start < FIRST.plus(cut).first_day()]
    for item in check_salary(versions, credits, stopped, TODAY).evidence:
        if item.outcome is Outcome.MISSED:
            assert full[item.pay_month] is Outcome.MISSED
