"""Known statement layouts, by file family. Order matters only if two layouts could recognize the same file."""

from __future__ import annotations

from collections.abc import Sequence

from ..ocr_tabular import norm_text
from .base import Bank, Layout, SheetBank
from .bice_xlsx import BiceTarjetaMovimientos
from .card_statement import ChileanCardStatement
from .santander import SantanderCuentaMatica
from .santander_xlsx import SantanderCuentaCorrienteXlsx

# Documents (PDF or image): word boxes from the text layer, or OCR for scans and photos.
BANKS: tuple[Bank, ...] = (SantanderCuentaMatica(), ChileanCardStatement())
# Spreadsheet exports (.xlsx): read cell by cell, never through PDF or OCR.
SHEET_BANKS: tuple[SheetBank, ...] = (SantanderCuentaCorrienteXlsx(), BiceTarjetaMovimientos())


def detect(first_page_text: str, banks: Sequence[Layout] = BANKS) -> Layout | None:
    text = norm_text(first_page_text)
    return next((bank for bank in banks if bank.recognizes(text)), None)
