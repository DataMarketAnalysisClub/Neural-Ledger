"""StatementReader adapter: ocr_tabular for the pixels and boxes, a Bank for the meaning."""

from __future__ import annotations

from collections.abc import Sequence

from ....application.ports import StatementReaderUnavailable, StatementUnreadable
from ....domain.statements.model import BankStatement
from .banks import BANKS, detect
from .banks.base import Bank
from .ocr_tabular import HeaderNotFound, MissingDependency, TableError, read_pages, rebuild


class OcrStatementReader:
    """Reads text-layer PDFs with the `pdf` extra; scans and photos also need the `ocr` extra."""

    def __init__(self, banks: Sequence[Bank] = BANKS, *, model_dir: str | None = None, gpu: bool = False) -> None:
        self._banks = tuple(banks)
        self._ocr = {"gpu": gpu, "model_dir": model_dir}

    def read(self, content: bytes) -> BankStatement:
        try:
            pages = read_pages(content, **self._ocr)
            bank = detect(pages[0].text if pages else "", self._banks)
            if bank is None:
                known = ", ".join(b.name for b in self._banks)
                raise StatementUnreadable(f"not a statement layout this reader knows (known: {known})")
            tables = []
            for page in pages:
                try:
                    tables.append(rebuild(page, bank.table))
                except HeaderNotFound:
                    continue  # a page of notices only; a page that lost movements fails reconciliation instead
            return bank.parse(tables)
        except MissingDependency as exc:
            raise StatementReaderUnavailable(str(exc)) from exc
        except TableError as exc:
            raise StatementUnreadable(str(exc)) from exc
