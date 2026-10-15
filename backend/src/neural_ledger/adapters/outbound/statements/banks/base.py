"""One subclass per statement layout. Adding a bank = one subclass + register it in `banks/__init__.py`.

Two families, by what the file is:
  - `SheetBank`: a spreadsheet export (.xlsx). Reads cells directly; no PDF or OCR involved.
  - `Bank`: a document (PDF or image). Reads word boxes from `ocr_tabular`: the PDF's text
    layer when it has one, OCR only for scans and photos.

Every layout knows:
  1. how to recognize its file (`recognizes`, from the first page's or sheet's normalized text);
  2. what kind of account it is (`account_type`): a credit card statement carries obligations
     (amount due, minimum, due date, cuotas), and its payments are never income;
  3. what the rows mean (`parse` / `read`): dates, amounts and signs, daily balances, printed totals.

A document Bank also says where its table is (`table`: header words and where the table ends),
which `ocr_tabular` uses to rebuild one Table per page; a layout whose lines are regular enough
overrides `read` and parses page lines instead.

Parsing is strict: a cell that is not what the layout says raises TableError instead of being
guessed. Reconciliation (domain) then checks that what was read adds up.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import ClassVar

from .....domain.ledger.entities import AccountType
from .....domain.statements.model import BankStatement
from ..ocr_tabular import HeaderNotFound, Page, Table, TableError, TableSpec, norm_text, rebuild
from ..spreadsheet import Sheet

# Thousands groups; the separator may be lost or turned into a space or '_' by OCR ('3 280', '1 _ 097 .805').
_THOUSANDS = re.compile(r"^-?\d{1,3}(\.?\d{3})*$")


class Layout(ABC):
    code: ClassVar[str]  # stable id stored with each statement, e.g. "santander_cl_cuentamatica"
    name: ClassVar[str]
    currency: ClassVar[str] = "CLP"
    account_type: ClassVar[AccountType] = AccountType.CHECKING

    @abstractmethod
    def recognizes(self, first_page_text: str) -> bool:
        """True if this layout produced the file. Called with `norm_text`-ed text of the first page or sheet."""


class Bank(Layout):
    """A document layout (PDF or image)."""

    table: ClassVar[TableSpec]

    def read(self, pages: Sequence[Page]) -> tuple[BankStatement, ...]:
        """Pages → the statements they hold. By default one, from one table per page."""
        tables = []
        for page in pages:
            try:
                tables.append(rebuild(page, self.table))
            except HeaderNotFound:
                continue  # a page of notices only; a page that lost movements fails reconciliation instead
        return (self.parse(tables),)

    def parse(self, tables: Sequence[Table]) -> BankStatement:
        """Tables (one per page, in order) → statement. Raise TableError on anything unexpected."""
        raise NotImplementedError(f"{type(self).__name__} reads page lines, not tables")


class SheetBank(Layout):
    """A spreadsheet export layout (.xlsx)."""

    @abstractmethod
    def parse(self, sheets: Sequence[Sheet]) -> BankStatement:
        """Sheets (in tab order) → statement. Raise TableError on anything unexpected."""


def parse_clp(text: str) -> int | None:
    """'1.116.492' → 1116492; '' → None. CLP has no minor unit, so pesos are minor units.

    Tolerant of lost or noisy separators, strict about digit groups. A misread digit still
    parses, which is why every amount is reconciled against the printed totals afterwards."""
    cleaned = re.sub(r"[\s_$]", "", text)
    if not cleaned:
        return None
    if not _THOUSANDS.match(cleaned):
        raise TableError(f"not an amount: {text!r}")
    return int(cleaned.replace(".", ""))


def parse_money(text: str, decimals: int) -> int | None:
    """A printed amount in minor units, Chilean style: '.' groups thousands, ',' marks decimals.

    '$ -323.516' → -323516 (CLP, 0 decimals); 'US$ 1.000,00' → 100000 and '-22,41' → -2241 (USD, 2).
    Strict: decimals, when printed, must be exactly `decimals` digits, so '22,4' or a CLP '1.000,50'
    is refused.
    """
    cleaned = re.sub(r"(US\$|USD|CLP|\$|\s)", "", text, flags=re.IGNORECASE)
    if not cleaned:
        return None
    match = re.fullmatch(r"(-?)(\d{1,3}(?:\.\d{3})*|\d+)(?:,(\d+))?", cleaned)
    if not match:
        raise TableError(f"not an amount: {text!r}")
    sign, whole, fraction = match.group(1), match.group(2).replace(".", ""), match.group(3)
    if fraction is not None and len(fraction) != decimals:
        raise TableError(f"not an amount with {decimals} decimals: {text!r}")
    value = int(whole) * 10**decimals + int(fraction or 0)
    return -value if sign else value


def cell_money(text: str, decimals: int) -> int | None:
    """A spreadsheet number cell ('8.22', '-120990', '20') in minor units. Exact: no float involved."""
    cleaned = text.strip()
    if not cleaned:
        return None
    try:
        value = Decimal(cleaned) * 10**decimals
    except InvalidOperation as exc:
        raise TableError(f"not a number: {text!r}") from exc
    if value != value.to_integral_value():
        raise TableError(f"{text!r} has more than {decimals} decimals")
    return int(value)


def full_date(text: str) -> date:
    """'27/08/2026' or '27/08/26' → date."""
    cleaned = text.strip()
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    raise TableError(f"not a date: {text!r}")


def day_month(text: str, period_end: date) -> date:
    """'02/09' → the latest such date not after the period end, so Dec→Jan statements get the right year."""
    # Searched, not matched: OCR reads the table's left rule as '1' or '|' ('102/09', '|16/09').
    match = re.search(r"(\d{1,2})/(\d{1,2})$", text.strip())
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


def column_index(header: Sequence[str], name: str) -> int:
    """Index of the header cell naming `name`. OCR reads table rules as letters ('INUMERO',
    '[DEPOSITOS') and swaps glyphs ('BUC' for 'SUC'), so a cell matches if its first word
    contains `name` or is one edit away from it."""
    for i, cell in enumerate(header):
        words = norm_text(cell).split()
        if words and (name in words[0] or _one_edit(words[0], name)):
            return i
    raise TableError(f"column {name!r} not found in header {list(header)!r}")


def _one_edit(a: str, b: str) -> bool:
    if abs(len(a) - len(b)) > 1 or min(len(a), len(b)) < 3:
        return False
    i = 0
    while i < min(len(a), len(b)) and a[i] == b[i]:
        i += 1
    return a[i + 1 :] == b[i + 1 :] or a[i:] == b[i + 1 :] or a[i + 1 :] == b[i:]
