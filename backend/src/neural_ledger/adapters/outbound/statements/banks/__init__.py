"""Known statement layouts. Order matters only if two banks could recognize the same page."""

from __future__ import annotations

from collections.abc import Sequence

from ..ocr_tabular import norm_text
from .base import Bank
from .santander import SantanderCuentaMatica

BANKS: tuple[Bank, ...] = (SantanderCuentaMatica(),)


def detect(first_page_text: str, banks: Sequence[Bank] = BANKS) -> Bank | None:
    text = norm_text(first_page_text)
    return next((bank for bank in banks if bank.recognizes(text)), None)
