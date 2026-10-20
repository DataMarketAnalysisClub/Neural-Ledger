"""ADR-039: the spending check-in for the pay cycle of today, against Camila's conservative forecast (P80 = 900,000
a cycle outside December) and her protected surplus of 20,000 (E05)."""

from __future__ import annotations

from datetime import date

import pytest

from neural_ledger.domain.finance.spending import LoggedSpend, spending_caveats, spending_check, spending_facts

NOVEMBER = date(2026, 11, 1)  # inside the first projected cycle: 2026-10-30 (payday) to 2026-11-29, 29 days with today
OCTOBER = date(2026, 10, 19)  # inside the cycle before it: 2026-09-30 to 2026-10-29, 11 days with today
AS_OF = NOVEMBER


def _spent(amount: int, on: date = AS_OF, category: str = "groceries", ref: str = "r") -> LoggedSpend:
    return LoggedSpend(on, amount, category, "receipt", ref)


def test_with_nothing_logged_the_whole_assumption_is_left(camila):
    c = spending_check(camila, (), AS_OF, 20_000)
    assert (c.cycle.year, c.cycle.month, c.window_start, c.window_end, c.projected) == (2026, 11, date(2026, 10, 30), date(2026, 11, 29), True)
    assert (c.assumed, c.logged, c.left, c.days_left, c.per_day) == (900_000, 0, 900_000, 29, 31_034)
    assert (c.overspend, c.surplus_after, c.categories) == (0, 20_000, ())
    assert spending_caveats(c) == ()


def test_a_receipt_lowers_what_is_left_and_the_per_day_rounds_down(camila):
    c = spending_check(camila, (_spent(12_990),), AS_OF, 20_000)
    assert (c.logged, c.left, c.per_day) == (12_990, 887_010, 30_586)  # 887,010 / 29 = 30,586.6
    assert c.per_day * c.days_left <= c.left
    assert [(x.category, x.assumed, x.logged) for x in c.categories] == [("groceries", 330_000, 12_990)]


def test_the_cycle_is_the_one_of_today_and_later_days_divide_by_fewer_days(camila):
    assert spending_check(camila, (), date(2026, 11, 28), 20_000).days_left == 2
    assert spending_check(camila, (), date(2026, 11, 30), 20_000).cycle.month == 12  # payday opens the next cycle
    december = spending_check(camila, (), date(2026, 12, 1), 20_000)
    assert december.assumed == 1_470_000  # P80 900,000 x the December factor 49/30


def test_in_the_cycle_before_the_forecast_receipts_count_but_the_surplus_is_not_touched(camila):
    c = spending_check(camila, (_spent(12_990, date(2026, 10, 16)),), OCTOBER, 20_000)
    assert (c.cycle.month, c.window_start, c.window_end, c.days_left, c.projected) == (10, date(2026, 9, 30), date(2026, 10, 29), 11, False)
    assert (c.logged, c.left, c.per_day) == (12_990, 887_010, 80_637)
    over = spending_check(camila, (_spent(905_000, date(2026, 10, 16)),), OCTOBER, 20_000)
    assert (over.overspend, over.surplus_after) == (5_000, 20_000)
    assert [(w.code, w.must_mention) for w in spending_caveats(over)] == [("SPENDING_ABOVE_FORECAST", ("counts on", "pronóstico", "cuenta el pronóstico"))]


def test_only_spending_inside_the_window_counts(camila):
    logged = (_spent(5_000, date(2026, 10, 29), ref="before"), _spent(7_000, date(2026, 11, 30), ref="after"), _spent(1_000, ref="in"))
    c = spending_check(camila, logged, AS_OF, 20_000)
    assert (c.logged, c.logged_items) == (1_000, 1)


def test_overspend_comes_out_of_the_protected_surplus(camila):
    c = spending_check(camila, (_spent(905_000),), AS_OF, 20_000)
    assert (c.left, c.per_day, c.overspend, c.surplus_after) == (-5_000, 0, 5_000, 15_000)
    assert [w.code for w in spending_caveats(c)] == ["SPENDING_ABOVE_FORECAST"]


def test_past_the_surplus_a_conservative_month_breaches_the_floor(camila):
    c = spending_check(camila, (_spent(925_000),), AS_OF, 20_000)
    assert (c.overspend, c.surplus_after) == (25_000, -5_000)
    assert [w.code for w in spending_caveats(c)] == ["SPENDING_BREACHES_FLOOR"]


def test_every_figure_is_a_fact(camila):
    c = spending_check(camila, (_spent(12_990),), AS_OF, 20_000)
    facts = {f.key: f.value for f in spending_facts(c, "CLP")}
    assert {k: facts[k] for k in ("spending.assumed", "spending.logged", "spending.left", "spending.per_day", "spending.days_left")} == {
        "spending.assumed": 900_000, "spending.logged": 12_990, "spending.left": 887_010, "spending.per_day": 30_586, "spending.days_left": 29,
    }
    assert facts["spending.groceries.assumed"] == 330_000 and facts["protected_surplus"] == 20_000


def test_money_stays_integer(camila):
    c = spending_check(camila, (_spent(1),), AS_OF, 20_000)
    assert all(isinstance(v, int) for v in (c.assumed, c.logged, c.left, c.per_day, c.overspend, c.surplus_after))


@pytest.mark.parametrize("amount", [0, 1, 899_999, 900_000, 900_001])
def test_left_plus_logged_is_the_assumption(camila, amount):
    c = spending_check(camila, (_spent(amount),), AS_OF, 20_000)
    assert c.left + c.logged == c.assumed and c.overspend == max(0, -c.left)


def test_a_forecast_already_below_the_floor_is_not_blamed_on_spending(camila):
    c = spending_check(camila, (), AS_OF, -1_940_000)  # Diego's case: the conservative forecast breaches without any spending
    assert (c.overspend, c.surplus_after) == (0, -1_940_000)
    assert spending_caveats(c) == ()
    worse = spending_check(camila, (_spent(901_000),), AS_OF, -1_940_000)
    assert [w.code for w in spending_caveats(worse)] == ["SPENDING_BREACHES_FLOOR"]
