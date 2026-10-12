"""Pay-cycle calendar shared by the estimators and the ledger generator.

Forecast cycles are labelled by the month whose spending they fund (see forecast.py and
shared/month.py): the salary credited on the last business day of month M-1 funds cycle M.
So cycle M runs from payday(M-1) inclusive to payday(M) exclusive, and its trough is the
balance on the day before payday(M).

Simplification (documented in docs/SCOPE.md, F11): a business day is any weekday. Chilean
public and bank holidays are ignored (e.g. 2025-10-31 is a public holiday and 12-31 a bank
holiday in Chile); on synthetic data this changes nothing.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

from ..shared.month import Month


def payday(month: Month) -> date:
    """Last weekday of the calendar month."""
    day = date(month.year, month.month, calendar.monthrange(month.year, month.month)[1])
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def cycle_start(cycle: Month) -> date:
    return payday(cycle.plus(-1))


def cycle_end(cycle: Month) -> date:
    """Last day of the cycle: the day before payday(cycle), where the trough is measured."""
    return payday(cycle) - timedelta(days=1)


def cycle_of(day: date) -> Month:
    month = Month.of(day)
    return month.plus(1) if day >= payday(month) else month


def is_eve_of_payday(day: date) -> bool:
    following = day + timedelta(days=1)
    return following == payday(Month.of(following))
