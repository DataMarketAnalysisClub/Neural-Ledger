"""ADR-049 §5-9: a declared salary enters the income by decomposition. The worked examples A-F of the ADR, run on
hand-built ledgers through the real estimator and salary check.

Ledger: 12 window cycles; each cycle's salary is credited on the payday that opens it; "others" is 150,000 credited
mid-cycle in 6 of the 12 cycles (observed P50 1,075,000 and P20 1,000,000 with a 1,000,000 salary; others P50
75,000 and P20 0).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from neural_ledger.domain.finance.estimation import canonical_window, estimate_model
from neural_ledger.domain.finance.income_memory import (
    RAISE_ASSUMED,
    SALARY_CONFLICT,
    SALARY_DIFFERS,
    SALARY_UNIDENTIFIED,
    overlay_income,
)
from neural_ledger.domain.finance.model import IncomeStep, Scenario
from neural_ledger.domain.finance.params import FC_0_1
from neural_ledger.domain.finance.paycycle import cycle_of, cycle_start, payday
from neural_ledger.domain.ledger.entities import (
    Account,
    AccountType,
    IncomeProfile,
    IncomeType,
    LedgerSnapshot,
    Transaction,
    TransactionKind,
)
from neural_ledger.domain.memory.catalog import Declaration, ProfileOrigin, SalaryNet, Source
from neural_ledger.domain.memory.salary_check import AccountSpan, Credit, check_salary
from neural_ledger.domain.shared.month import Month

BASE = 1_000_000
OTHERS = 150_000


def ledger(last: Month, salary: dict[Month, int] | None = None, *, others: bool = True, contracted: int | None = None) -> LedgerSnapshot:
    """12 cycles ending in `last`; `salary` maps a pay month to its credit (default BASE; 0 = none that month)."""
    salary = salary or {}
    txns: list[Transaction] = []
    for i, cycle in enumerate(last.plus(-k) for k in reversed(range(12))):
        start = cycle_start(cycle)
        paid = salary.get(cycle.plus(-1), BASE)
        if paid:
            txns.append(Transaction(f"sal_{cycle}", "checking", start, paid, "EMPLEADOR SPA", "salary", TransactionKind.INCOME))
        if others and i % 2:
            txns.append(Transaction(f"oth_{cycle}", "checking", start + timedelta(days=10), OTHERS, "HONORARIOS", "other_income", TransactionKind.INCOME))
        for j, (merchant, category, amount) in enumerate((("JUMBO", "groceries", 100_000 + 37_000 * (i % 4)), ("LIDER EXPRESS", "groceries", 60_000 + 23_000 * (i % 3)), ("COPEC", "transport", 40_000 + 17_000 * (i % 5)))):
            txns.append(Transaction(f"spd_{cycle}_{j}", "checking", start + timedelta(days=3 + 4 * j + i % 3), -amount, merchant, category, TransactionKind.PURCHASE))
    return LedgerSnapshot(
        "u1", "CLP", payday(last) - timedelta(days=1), "test", (Account("checking", AccountType.CHECKING, 900_000, "CLP"),),
        tuple(txns), (), (), IncomeProfile(IncomeType.SALARIED, contracted, "last_business_day"),
    )


def declared(version: int, amount: int, effective_from: str, confirmed: date = date(2025, 8, 1)) -> Declaration:
    return Declaration(
        f"mem_{version}", "chn_1", version, "u1", SalaryNet(amount, Month.parse(effective_from)),
        datetime(confirmed.year, confirmed.month, confirmed.day, tzinfo=UTC), Source.PROFILE, ProfileOrigin(), f"evt_{version}",
    )


def overlay(snapshot: LedgerSnapshot, versions: list[Declaration], *, extra: list[Credit] = ()):
    model = estimate_model(snapshot, FC_0_1).data
    window = canonical_window(snapshot, FC_0_1)
    credits = [Credit("st_1", t.txn_id, t.amount, t.date) for t in snapshot.transactions if t.kind is TransactionKind.INCOME] + list(extra)
    spans = (AccountSpan("checking", date(2024, 1, 1), snapshot.as_of),)
    check = check_salary(versions, credits, spans, snapshot.as_of + timedelta(days=1)) if versions else None
    return model, overlay_income(model, window, versions, check, FC_0_1)


def income(result, cycle: str) -> tuple[int, int]:
    month = Month.parse(cycle)
    return result.income.for_month(Scenario.TYPICAL, month), result.income.for_month(Scenario.CONSERVATIVE, month)


SEPTEMBER = ledger(Month(2026, 9))  # as_of 2026-09-29; first projected cycle 2026-10, funded by payday 2026-09-30


def test_the_observed_income_of_the_ledger():
    model = estimate_model(SEPTEMBER, FC_0_1).data
    assert (model.income.typical, model.income.conservative) == (1_075_000, 1_000_000)


def test_without_memory_nothing_changes():
    model, result = overlay(SEPTEMBER, [])
    assert not result.applied and result.income == model.income and result.warnings == ()


def test_a_constant_salary_declared_as_is_changes_nothing():  # example A
    model, result = overlay(SEPTEMBER, [declared(1, BASE, "2025-09")])
    assert result.applied and result.warnings == ()
    assert (result.others_typical, result.others_conservative) == (75_000, 0)
    for k in range(48):
        cycle = str(Month(2026, 10).plus(k))
        assert income(result, cycle) == (model.income.typical, model.income.conservative) == (1_075_000, 1_000_000)


def test_a_raise_lifts_the_typical_income_only_from_the_cycle_it_funds():  # example B
    _, result = overlay(SEPTEMBER, [declared(1, BASE, "2025-09"), declared(2, 1_200_000, "2026-10", date(2026, 9, 15))])
    assert income(result, "2026-10") == (1_075_000, 1_000_000)  # funded by September's payday: the old salary
    assert income(result, "2026-11") == (1_275_000, 1_000_000)  # the raise, not supported yet: conservative stays
    assert result.warnings == (RAISE_ASSUMED,)
    assert result.income.monthly == (IncomeStep(Month(2026, 10), 1_075_000, 1_000_000), IncomeStep(Month(2026, 11), 1_275_000, 1_000_000))


def test_two_matches_of_the_raise_support_it_and_it_is_counted_once():  # example C
    december = ledger(Month(2026, 12), {Month(2026, 10): 1_200_000, Month(2026, 11): 1_200_000})
    model, result = overlay(december, [declared(1, BASE, "2025-09"), declared(2, 1_200_000, "2026-10", date(2026, 9, 15))])
    assert (model.income.typical, model.income.conservative) == (1_150_000, 1_000_000)  # the raise is already in P50:
    assert income(result, "2027-01") == (1_275_000, 1_200_000)  # adding the difference to it would count it twice
    assert result.warnings == ()
    assert (result.others_typical, result.others_conservative) == (75_000, 0)  # the raised salaries left by txn_id


def test_one_match_of_the_raise_is_not_enough():
    november = ledger(Month(2026, 11), {Month(2026, 10): 1_200_000})
    _, result = overlay(november, [declared(1, BASE, "2025-09"), declared(2, 1_200_000, "2026-10", date(2026, 9, 15))])
    assert income(result, "2026-12") == (1_275_000, 1_000_000) and result.warnings == (RAISE_ASSUMED,)


def test_a_declared_decrease_caps_both_scenarios():  # example D
    _, result = overlay(SEPTEMBER, [declared(1, BASE, "2025-09"), declared(2, 900_000, "2026-10", date(2026, 9, 15))])
    assert income(result, "2026-11") == (975_000, 900_000) and result.warnings == ()


def test_a_conflict_turns_memory_off():  # example E
    late = ledger(Month(2026, 9), {Month(2026, 7): 0, Month(2026, 8): 0})
    model, result = overlay(late, [declared(1, BASE, "2025-09")])
    assert not result.applied and result.warnings == (SALARY_CONFLICT,) and result.income == model.income


def test_a_varying_salary_declared_at_its_median():  # example F, pending the gate
    varying = ledger(Month(2026, 9), {Month(2025, 9).plus(k): (980_000 if k % 2 else 1_020_000) for k in range(12)}, others=False)
    model, result = overlay(varying, [declared(1, BASE, "2025-09")])
    assert (model.income.typical, model.income.conservative) == (1_000_000, 980_000)
    assert income(result, "2026-10") == (1_000_000, 1_000_000)  # 20,000 above the observed P20: Roles A and E decide


def test_a_salary_missing_from_one_cycle_leaves_memory_saved_only():
    gap = ledger(Month(2026, 9), {Month(2026, 3): 0})
    model, result = overlay(gap, [declared(1, BASE, "2025-09")])
    assert not result.applied and result.warnings == (SALARY_UNIDENTIFIED,) and result.income == model.income


def test_a_first_declaration_without_a_verified_base_has_no_effect():
    model, result = overlay(SEPTEMBER, [declared(1, 1_200_000, "2026-10", date(2026, 9, 15))])
    assert not result.applied and result.warnings == (SALARY_UNIDENTIFIED,) and result.income == model.income


def test_an_inflated_declaration_never_lifts_the_conservative_income():
    _, result = overlay(SEPTEMBER, [declared(1, BASE, "2025-09"), declared(2, 100_000_000, "2026-10", date(2026, 9, 15))])
    assert income(result, "2026-11")[1] == 1_000_000


def test_two_successive_raises_wait_for_their_own_evidence():
    versions = [declared(1, BASE, "2025-09"), declared(2, 1_100_000, "2026-10", date(2026, 9, 15)), declared(3, 1_200_000, "2026-12", date(2026, 9, 16))]
    _, result = overlay(SEPTEMBER, versions)
    assert [income(result, c) for c in ("2026-10", "2026-11", "2027-01")] == [(1_075_000, 1_000_000), (1_175_000, 1_000_000), (1_275_000, 1_000_000)]
    january = ledger(Month(2026, 12), {Month(2026, 10): 1_100_000, Month(2026, 11): 1_100_000})
    _, result = overlay(january, versions)
    assert income(result, "2027-01") == (1_275_000, 1_100_000)  # the second raise rests on the first one's two matches


def test_a_future_declaration_keeps_the_cycles_before_it():
    _, result = overlay(SEPTEMBER, [declared(1, BASE, "2025-09"), declared(2, 1_500_000, "2027-06", date(2026, 9, 15))])
    assert [income(result, c) for c in ("2026-10", "2027-06", "2027-07")] == [(1_075_000, 1_000_000)] * 2 + [(1_575_000, 1_000_000)]


def test_matched_credits_below_the_declaration_are_used():
    lower = ledger(Month(2026, 9), {Month(2025, 9).plus(k): 960_000 for k in range(12)})
    _, result = overlay(lower, [declared(1, BASE, "2025-09")])
    assert income(result, "2026-10") == (1_075_000, 960_000) and result.warnings == (SALARY_DIFFERS,)  # typical: as declared


def test_an_early_salary_is_identified_by_its_expected_payday():
    early = ledger(Month(2026, 9))
    moved = tuple(
        Transaction(t.txn_id, t.account_id, t.date - timedelta(days=2), t.amount, t.merchant_raw, t.category, t.kind)
        if t.txn_id == "sal_2026-05" else t for t in early.transactions
    )  # payday 2026-04-30 is a Thursday; two days early is in cycle 2026-04 for the estimator
    early = LedgerSnapshot(early.user_id, "CLP", early.as_of, "test", early.accounts, moved, (), (), early.income_profile)
    assert cycle_of(date(2026, 4, 28)) == Month(2026, 4)
    _, result = overlay(early, [declared(1, BASE, "2025-09")])
    assert result.applied and income(result, "2026-10") == (1_075_000, 1_000_000)


def test_a_contracted_net_is_never_overlaid():
    model, result = overlay(ledger(Month(2026, 9), contracted=BASE), [declared(1, 1_200_000, "2025-09")])
    assert model.income.method == "contracted" and not result.applied and result.income == model.income


@pytest.mark.parametrize("amount", [1_000_000, 1_000_001])
def test_the_fingerprint_follows_the_declarations(amount):
    _, base = overlay(SEPTEMBER, [declared(1, BASE, "2025-09")])
    _, other = overlay(SEPTEMBER, [declared(1, amount, "2025-09")])
    assert (base.fingerprint == other.fingerprint) is (amount == BASE)
