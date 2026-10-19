"""ReceiptReader adapter: the statement reader's page pipeline, reused for receipts (ADR-039).

    bytes ─┬─ .xlsx / .xls ─► "xlsx": always a statement, nothing read here
           └─ PDF / image ─► ocr_tabular.read_pages (text layer, or OCR for scans and photos) ─► page lines
                              ├─ peek: the first page's text, for routing
                              └─ read_receipt: boleta.parse_receipt + stamp.decode_stamp (SII timbre, optional)

The pages of the last file peeked are kept (one entry) until it is read as a receipt or another file is peeked, so
routing and reading a photo run OCR once.
"""

from __future__ import annotations

import hashlib
import threading

from ....application.ports import DocumentText, StatementReaderUnavailable, StatementUnreadable
from ....domain.receipts.model import ReadReceipt
from ..statements.ocr_tabular import MissingDependency, Page, TableError, detect_format, read_pages
from ..statements.spreadsheet import is_legacy_xls, is_xlsx
from .boleta import parse_receipt
from .stamp import decode_stamp


class ReceiptFileReader:
    """Text-layer PDFs need the `pdf` extra; photos and scans `ocr`; the SII stamp `receipts` (all optional)."""

    name = "boleta-0.1"

    def __init__(self, *, model_dir: str | None = None, gpu: bool = False) -> None:
        self._ocr = {"gpu": gpu, "model_dir": model_dir}
        self._lock = threading.Lock()
        self._cached: tuple[str, list[Page]] | None = None

    def peek(self, content: bytes) -> DocumentText:
        if is_xlsx(content) or is_legacy_xls(content):
            return DocumentText("xlsx", "")
        file_format = detect_format(content)
        if file_format is None:
            raise StatementUnreadable("unsupported format: expected a spreadsheet, a PDF or an image")
        pages = self._pages(content)
        return DocumentText(file_format, pages[0].text if pages else "")

    def read_receipt(self, content: bytes) -> ReadReceipt:
        file_format = detect_format(content)
        if file_format is None:
            raise StatementUnreadable("unsupported format: a receipt is a PDF or an image")
        pages = self._pages(content)
        with self._lock:
            self._cached = None  # the raw text holds personal data: keep it no longer than one import
        lines = [line for page in pages for line in page.lines]
        if not lines:
            raise StatementUnreadable("no text could be read from the receipt")
        source = "text" if all(page.source == "text" for page in pages) else "ocr"
        return parse_receipt(lines, source, decode_stamp(content, file_format))

    def _pages(self, content: bytes) -> list[Page]:
        key = hashlib.sha256(content).hexdigest()
        with self._lock:
            if self._cached is not None and self._cached[0] == key:
                return self._cached[1]
        try:
            pages = read_pages(content, **self._ocr)
        except MissingDependency as exc:
            raise StatementReaderUnavailable(str(exc)) from exc
        except TableError as exc:
            raise StatementUnreadable(str(exc)) from exc
        with self._lock:
            self._cached = (key, pages)
        return pages
