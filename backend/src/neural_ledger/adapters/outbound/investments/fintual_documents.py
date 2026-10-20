"""InvestmentDocumentReader adapter: the PDF documents Fintual issues to its clients (ADR-044).

    bytes ─► statements/ocr_tabular.read_pages (text layer; OCR for a scan with the `ocr` extra) ─► lines
          ├─ "INVESTMENT STATEMENT": one row per fund and series ("FM Fintual Risky Norris A 132,2389 $4.316,6320
          │   $570.827"), the "Total $..." line and the day of the balances ("declares that on October 14, 2026")
          └─ "CERTIFICADO DE TRANSACCIONES": one row per contribution or withdrawal ("14/10/2026 <goal> Risky Norris A
              12,3456 0 4.316,6320 132,2389 $53.290 0 Transferencia electronica $570.827")

Only rows and the day are read: the holder's name and RUT in the preamble are never extracted, and the text is
dropped once read. Numbers are Chilean (dot thousands, comma decimals); a lone 0 is an empty cell. A row that does
not parse makes the whole file unreadable, so a document is never read with rows silently missing. Whether the rows
add up is the domain's call (domain/investments/documents.py).
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation

from ....application.ports import StatementReaderUnavailable, StatementUnreadable
from ....domain.investments.documents import FundMovement, FundPosition, InvestmentDocumentKind, ReadInvestmentDocument
from ..statements.ocr_tabular import MissingDependency, TableError, detect_format, norm_text, read_pages

_NUM = r"\d+(?:\.\d{3})*(?:,\d+)?"
_INT = r"\d+(?:\.\d{3})*"
_PESOS = rf"\$?\s?{_INT}"
# Fintual's funds: a risk level and a name, sometimes a number ("Risky Norris", "Very Conservative Streep",
# "Moderate Brad 107"). The goal's name comes before it and may hold any words, so the fund is found from the right.
_FUND = r"(?:Very\s+)?(?:Risky|Moderate|Conservative)\s+[A-Z][A-Za-z]*(?:\s+\d+)?"
_SERIES = r"[A-Z0-9]{1,6}"

_HOLDING = re.compile(
    rf"^(?:FM\s+)?Fintual\s+(?P<fund>.+?)\s+(?P<series>{_SERIES})\s+(?P<shares>{_NUM})\s+\$\s?(?P<value>{_NUM})\s+\$\s?(?P<balance>{_INT})$"
)
_ROW_START = re.compile(r"^(?:FM\s+)?Fintual\s")  # a fund row starts with the fund's full name...
_ROW_END = re.compile(rf"\$\s?{_INT}$")  # ...and ends with its balance; any such line that does not parse is an error
_TOTAL = re.compile(rf"^Total\s+\$\s?(?P<total>{_INT})$", re.I)
_MOVEMENT_START = re.compile(r"^\d{2}/\d{2}/\d{4}\s")
_MOVEMENT = re.compile(
    rf"^(?P<day>\d{{2}}/\d{{2}}/\d{{4}})\s+(?P<goal>.+?)\s+(?P<fund>{_FUND})\s+(?P<series>{_SERIES})\s+"
    rf"(?P<shares_in>{_NUM})\s+(?P<shares_out>{_NUM})\s+(?P<value>{_NUM})\s+(?P<shares_after>{_NUM})\s+"
    rf"(?P<pesos_in>{_PESOS})\s+(?P<pesos_out>{_PESOS})\s+(?P<channel>[^\d$]+?)\s+\$\s?(?P<pesos_after>{_INT})$"
)
_INTERNAL = re.compile(r"\binterno\b", re.I)  # "MLT interno": shares moved between the user's own goals or funds

_MONTHS = {
    name: number
    for number, names in enumerate(
        (
            ("january", "enero"), ("february", "febrero"), ("march", "marzo"), ("april", "abril"), ("may", "mayo"),
            ("june", "junio"), ("july", "julio"), ("august", "agosto"), ("september", "septiembre", "setiembre"),
            ("october", "octubre"), ("november", "noviembre"), ("december", "diciembre"),
        ),
        start=1,
    )
    for name in names
}
# The day of the balances, then the day the statement was issued: "declares that on October 14, 2026",
# "As of today, October 14, 2026", or in Spanish "al 14 de octubre de 2026".
_BALANCE_DAY = (
    re.compile(r"declares that on\s+(?P<month>[A-Za-z]+)\s+(?P<day>\d{1,2}),?\s+(?P<year>\d{4})", re.I),
    re.compile(r"\bal\s+(?P<day>\d{1,2})\s+de\s+(?P<month>[A-Za-z]+)\s+(?:de|del)\s+(?P<year>\d{4})", re.I),
    re.compile(r"as of today,?\s+(?P<month>[A-Za-z]+)\s+(?P<day>\d{1,2}),?\s+(?P<year>\d{4})", re.I),
)
MAX_LINES = 20_000  # far beyond a real certificate; a larger file is not one


class FintualDocumentReader:
    """Text-layer PDFs need the `pdf` extra; scans the `ocr` extra (both optional)."""

    name = "fintual-pdf-0.1"
    provider = "fintual"

    def __init__(self, *, model_dir: str | None = None, gpu: bool = False) -> None:
        self._ocr = {"gpu": gpu, "model_dir": model_dir}

    def read(self, content: bytes) -> ReadInvestmentDocument:
        if detect_format(content) != "pdf":
            raise StatementUnreadable("a Fintual statement is a PDF")
        try:
            pages = read_pages(content, **self._ocr)
        except MissingDependency as exc:
            raise StatementReaderUnavailable(str(exc)) from exc
        except TableError as exc:
            raise StatementUnreadable(str(exc)) from exc
        lines = [" ".join(text.split()) for page in pages for text, _ in page.lines]
        if len(lines) > MAX_LINES:
            raise StatementUnreadable("the file is too long for a Fintual statement")
        normalized = norm_text(" ".join(lines[:40]))
        if "fintual" not in normalized:
            raise StatementUnreadable("this is not a document issued by Fintual")
        if "certificado de transacciones" in normalized:
            return ReadInvestmentDocument(self.provider, InvestmentDocumentKind.MOVEMENTS, movements=_movements(lines))
        if "investment statement" in normalized or any(_HOLDING.match(line) for line in lines):
            positions, total = _holdings(lines)
            return ReadInvestmentDocument(self.provider, InvestmentDocumentKind.HOLDINGS, _balance_day(lines), positions, total)
        raise StatementUnreadable("this Fintual document is neither an investment statement nor a transactions certificate")


def _holdings(lines: list[str]) -> tuple[tuple[FundPosition, ...], int | None]:
    positions: list[FundPosition] = []
    total: int | None = None
    for line in lines:
        if total is None and (t := _TOTAL.match(line)):
            total = _int(t["total"])
            continue
        if not (_ROW_START.match(line) and _ROW_END.search(line)):
            continue
        m = _HOLDING.match(line)
        if m is None:
            raise StatementUnreadable("a fund row of the statement could not be read")
        positions.append(FundPosition(m["fund"], m["series"], _decimal(m["shares"]), _decimal(m["value"]), _int(m["balance"])))
    return tuple(positions), total


def _movements(lines: list[str]) -> tuple[FundMovement, ...]:
    movements: list[FundMovement] = []
    for line in lines:
        if not _MOVEMENT_START.match(line):
            continue
        m = _MOVEMENT.match(line)
        if m is None:
            raise StatementUnreadable("a movement of the certificate could not be read")
        movements.append(
            FundMovement(
                day=_day(m["day"]),
                goal=m["goal"],
                fund=" ".join(m["fund"].split()),
                series=m["series"],
                shares_in=_decimal(m["shares_in"]),
                shares_out=_decimal(m["shares_out"]),
                share_value=_decimal(m["value"]),
                shares_after=_decimal(m["shares_after"]),
                pesos_in=_int(m["pesos_in"]),
                pesos_out=_int(m["pesos_out"]),
                internal=bool(_INTERNAL.search(m["channel"])),
                pesos_after=_int(m["pesos_after"]),
            )
        )
    return tuple(movements)


def _balance_day(lines: list[str]) -> date | None:
    preamble = " ".join(lines[:12])
    for pattern in _BALANCE_DAY:
        m = pattern.search(preamble)
        if m is None:
            continue
        month = _MONTHS.get(m["month"].lower())
        if month is None:
            continue
        try:
            return date(int(m["year"]), month, int(m["day"]))
        except ValueError:
            return None
    return None


def _decimal(text: str) -> Decimal:
    try:
        return Decimal(text.replace("$", "").strip().replace(".", "").replace(",", "."))
    except InvalidOperation:
        raise StatementUnreadable("a number could not be read") from None


def _int(text: str) -> int:
    return int(text.replace("$", "").strip().replace(".", ""))


def _day(text: str) -> date:
    day, month, year = (int(part) for part in text.split("/"))
    try:
        return date(year, month, day)
    except ValueError:
        raise StatementUnreadable("a date of the certificate could not be read") from None
