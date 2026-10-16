"""StatementReader adapter: route the file by what it is, then let a layout give it meaning.

    bytes ─┬─ .xlsx (zip + xl/workbook.xml) ─► spreadsheet.read_workbook ─► SheetBank.parse
           │                                    standard library only: no PDF, no OCR
           └─ PDF / image ─► ocr_tabular.read_pages ─► Bank.read
                             text-layer PDFs use their words; only scans and photos run OCR

The route is chosen from the magic bytes, never from the file name.
"""

from __future__ import annotations

from collections.abc import Sequence

from ....application.ports import StatementReaderUnavailable, StatementUnreadable
from ....domain.statements.model import BankStatement
from .banks import BANKS, SHEET_BANKS, detect
from .banks.base import Bank, Layout, SheetBank
from .ocr_tabular import MissingDependency, TableError, read_pages
from .spreadsheet import is_legacy_xls, is_xlsx, read_workbook


class StatementFileReader:
    """Spreadsheets need nothing extra; text-layer PDFs need the `pdf` extra; scans and photos also `ocr`."""

    def __init__(
        self, banks: Sequence[Bank] = BANKS, sheet_banks: Sequence[SheetBank] = SHEET_BANKS, *, model_dir: str | None = None, gpu: bool = False
    ) -> None:
        self._banks = tuple(banks)
        self._sheet_banks = tuple(sheet_banks)
        self._ocr = {"gpu": gpu, "model_dir": model_dir}

    def read(self, content: bytes) -> tuple[BankStatement, ...]:
        try:
            if is_xlsx(content):
                return self._spreadsheet(content)
            if is_legacy_xls(content):
                raise StatementUnreadable("legacy .xls workbooks are not supported; save the file as .xlsx")
            return self._document(content)
        except MissingDependency as exc:
            raise StatementReaderUnavailable(str(exc)) from exc
        except TableError as exc:
            raise StatementUnreadable(str(exc)) from exc

    def _spreadsheet(self, content: bytes) -> tuple[BankStatement, ...]:
        sheets = read_workbook(content)
        bank = detect(sheets[0].text, self._sheet_banks)
        if bank is None:
            raise StatementUnreadable(_unknown("spreadsheet", self._sheet_banks))
        return (bank.parse(sheets),)

    def _document(self, content: bytes) -> tuple[BankStatement, ...]:
        pages = read_pages(content, **self._ocr)
        bank = detect(pages[0].text if pages else "", self._banks)
        if bank is None:
            raise StatementUnreadable(_unknown("document", self._banks))
        return bank.read(pages)


def _unknown(family: str, layouts: Sequence[Layout]) -> str:
    known = ", ".join(layout.name for layout in layouts)
    return f"not a statement layout this reader knows ({family}; known: {known})"
