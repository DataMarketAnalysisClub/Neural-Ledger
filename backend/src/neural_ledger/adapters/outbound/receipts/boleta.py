"""A Chilean receipt's fields from its lines of text (a PDF's text layer or OCR of a photo).

Boletas share a shape, not a layout: the store's name at the top, its RUT, "BOLETA ELECTRÓNICA N° <folio>", a date,
the items, then TOTAL (and on some, NETO and IVA). This parser looks for those words and keeps what it finds;
whatever it cannot find stays None, and domain/receipts `check` decides what that means. It never guesses a total
from the items.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date

from ....domain.receipts.model import ReadReceipt, ReceiptStamp

_RUT = re.compile(r"\b(\d{1,2}\.?\d{3}\.?\d{3}-[\dkK])\b")
_FOLIO = re.compile(r"(?:boleta(?:\s+electr[oó]nica)?|folio)\s*(?:n[°ºo]?\.?|nro\.?|#)?\s*[:#]?\s*(\d{1,10})\b", re.I)
_DATE = re.compile(r"\b(?:(\d{1,2})[/.-](\d{1,2})[/.-](\d{4}|\d{2})|(\d{4})-(\d{2})-(\d{2}))\b")
_MONEY = re.compile(r"\$?\s*(\d{1,3}(?:[.,]\d{3})+|\d+)(?![\d.,]*%)")
# OCR reads the last letter of TOTAL as "1", "]", "|" or "I" on thermal paper.
_TOTAL = re.compile(r"\btota\s?[l1I\]|](?![a-z])", re.I)
# A per-diner share, a count of items or a discount is printed on a TOTAL line but is never what was paid.
_NOT_TOTAL = re.compile(
    r"sub\s*-?\s*tota|\b(?:items?|art[ií]culos?|productos?|unidades|descuentos?|ahorro)\b|comensa|por persona", re.I
)
_NET = re.compile(r"\b(?:monto\s+)?neto\b", re.I)
_TAX = re.compile(r"\biva\b(?!\s+incluido)", re.I)
_HEADER_NOISE = re.compile(
    r"boleta|r\.?\s?u\.?\s?t|fecha|giro|direcci[oó]n|sucursal|casa matriz|s\.?i\.?i|res(?:oluci[oó]n)?\.?\s?ex|"
    r"producto|importe|\buds?\b|cant\.?\b|descripci[oó]n|detalle|precio|proforma|pendiente",
    re.I,
)
_LETTERS = re.compile(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{3,}")
# OCR often reads "$30.000" as "$30 . 000": a separator with spaces around it, followed by exactly three digits.
_SPACED_SEPARATOR = re.compile(r"(\d)\s*([.,])[.,\s]*(\d{3})(?!\d)")  # "8107,.320" has two
# Some thermal fonts make OCR read "$" as "8": "$11.980" comes back "811.980". Leading 8s are rare in prices (about one
# in twenty by Benford's law), so when most grouped amounts on a receipt start with an 8, that 8 is the dollar sign.
_GROUPED = re.compile(r"(?<![\d$])([$8]?)(\d{1,3}[.,]\d{3})(?![\d])")
_EIGHT_AS_DOLLAR = re.compile(r"(?<![\d$])8(\d{1,3}[.,]\d{3})(?!\d)")
MIN_EIGHTS = 3
# A run of four or more digits (a street number, a terminal or card reference) is never part of the store's name.
_LONG_NUMBER = re.compile(r"\d{4,}")
MAX_ISSUER = 80


def parse_receipt(lines: Sequence[tuple[str, float]], source: str, stamp: ReceiptStamp | None = None) -> ReadReceipt:
    """`lines` in reading order with each line's lowest confidence (1.0 for a text layer)."""
    if source == "ocr":
        lines = _dollar_signs(lines)
    texts = [text for text, _ in lines]
    joined = "\n".join(texts)
    total, total_confidence = _total(lines)
    return ReadReceipt(
        issuer=_issuer(texts),
        issued_on=_date(texts),
        total=total,
        folio=_first(_FOLIO, joined),
        issuer_rut=_first(_RUT, joined),
        net=_labelled(texts, _NET),
        tax=_labelled(texts, _TAX),
        stamp=stamp,
        source=source,
        confidence=None if source == "text" else total_confidence,
    )


def money(text: str) -> int | None:
    """The last amount on a line, as an integer of pesos ("$ 12.990" -> 12990); None if there is none."""
    found = _MONEY.findall(_SPACED_SEPARATOR.sub(r"\1\2\3", text))
    if not found:
        return None
    return int(re.sub(r"[.,]", "", found[-1]))


def _dollar_signs(lines: Sequence[tuple[str, float]]) -> list[tuple[str, float]]:
    cleaned = [(_SPACED_SEPARATOR.sub(r"\1\2\3", text), confidence) for text, confidence in lines]
    prefixes = [m.group(1) or m.group(2)[0] for text, _ in cleaned for m in _GROUPED.finditer(text)]
    eights = sum(1 for p in prefixes if p == "8")
    if eights < MIN_EIGHTS or eights * 2 <= len(prefixes):
        return cleaned
    return [(_EIGHT_AS_DOLLAR.sub(r"$\1", text), confidence) for text, confidence in cleaned]


def _total(lines: Sequence[tuple[str, float]]) -> tuple[int | None, float | None]:
    """The largest amount on a TOTAL line that is not a subtotal, an item count, a share or a tax line.

    Narrow receipts print the amount on the line under its label: a TOTAL line without one takes the next line's,
    when that line is only an amount.
    """
    best: tuple[int, float] | None = None
    for i, (text, confidence) in enumerate(lines):
        if not _TOTAL.search(text) or _NOT_TOTAL.search(text) or _NET.search(text) or _TAX.search(text):
            continue
        amount = money(_TOTAL.split(text, maxsplit=1)[-1])
        if amount is None and i + 1 < len(lines) and not _LETTERS.search(lines[i + 1][0]):
            amount, confidence = money(lines[i + 1][0]), min(confidence, lines[i + 1][1])
        if amount is not None and amount > 0 and (best is None or amount > best[0]):
            best = (amount, confidence)
    return best if best else (None, None)


def _labelled(texts: Sequence[str], label: re.Pattern[str]) -> int | None:
    for text in texts:
        if label.search(text) and not _TOTAL.search(text):
            return money(label.split(text, maxsplit=1)[-1])
    return None


def _issuer(texts: Sequence[str]) -> str:
    """The first line near the top that reads like a name: letters, and not a RUT, a date or the document's title."""
    for text in texts[:6]:
        noise = (_HEADER_NOISE, _RUT, _DATE, _LONG_NUMBER, _TOTAL)
        if _LETTERS.search(text) and "$" not in text and not any(p.search(text) for p in noise):
            return text.strip()[:MAX_ISSUER]
    return ""


def _date(texts: Sequence[str]) -> date | None:
    """The date on a line that says FECHA, else the first date printed."""
    ordered = [t for t in texts if re.search(r"fecha", t, re.I)] + list(texts)
    for text in ordered:
        for m in _DATE.finditer(text):
            parsed = _to_date(m)
            if parsed is not None:
                return parsed
    return None


def _to_date(m: re.Match[str]) -> date | None:
    try:
        if m.group(4):
            return date(int(m.group(4)), int(m.group(5)), int(m.group(6)))
        year = int(m.group(3))
        return date(year + 2000 if year < 100 else year, int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def _first(pattern: re.Pattern[str], text: str) -> str | None:
    m = pattern.search(text)
    return m.group(1) if m else None
