"""One `Bank` subclass per statement layout. Adding a bank = one subclass + register it in `banks/__init__.py`.

A Bank knows three things about its cartola:
  1. how to recognize it (`recognizes`, from the first page's text);
  2. where its table is (`table`: header words and where the table ends), which `ocr_tabular`
     uses to rebuild one Table per page;
  3. what the rows mean (`parse`): dates, charge/deposit columns, daily balances, printed totals.

Parsing is strict: a cell that is not what the layout says raises TableError instead of being
guessed. Reconciliation (domain) then checks that what was read adds up.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import date
from typing import ClassVar

from .....domain.statements.model import BankStatement
from ..ocr_tabular import Table, TableError, TableSpec, norm_text

_THOUSANDS = re.compile(r"^-?\d{1,3}(\.\d{3})*$")


class Bank(ABC):
    code: ClassVar[str]  # stable id stored with each statement, e.g. "santander_cl_cuentamatica"
    name: ClassVar[str]
    currency: ClassVar[str] = "CLP"
    table: ClassVar[TableSpec]

    @abstractmethod
    def recognizes(self, first_page_text: str) -> bool:
        """True if this layout printed the page. Called with `norm_text`-ed text."""

    @abstractmethod
    def parse(self, tables: Sequence[Table]) -> BankStatement:
        """Tables (one per page, in order) → statement. Raise TableError on anything unexpected."""


def parse_clp(text: str) -> int | None:
    """'1.116.492' → 1116492; '' → None. CLP has no minor unit, so pesos are minor units."""
    cleaned = text.replace("$", "").replace(" ", "")
    if not cleaned:
        return None
    if not _THOUSANDS.match(cleaned):
        raise TableError(f"not an amount: {text!r}")
    return int(cleaned.replace(".", ""))


def day_month(text: str, period_end: date) -> date:
    """'02/09' → the latest such date not after the period end, so Dec→Jan statements get the right year."""
    match = re.fullmatch(r"(\d{1,2})/(\d{1,2})", text.strip())
    if not match:
        raise TableError(f"not a day/month: {text!r}")
    day, month = int(match.group(1)), int(match.group(2))
    for year in (period_end.year, period_end.year - 1):
        try:
            candidate = date(year, month, day)
        except ValueError as exc:
            raise TableError(f"not a date: {text!r}") from exc
        if candidate <= period_end:
            return candidate
    raise TableError(f"date outside any plausible year: {text!r}")


def column_index(header: Sequence[str], prefix: str) -> int:
    """Index of the header cell starting with `prefix` (normalized)."""
    for i, cell in enumerate(header):
        if norm_text(cell).startswith(prefix):
            return i
    raise TableError(f"column {prefix!r} not found in header {list(header)!r}")
