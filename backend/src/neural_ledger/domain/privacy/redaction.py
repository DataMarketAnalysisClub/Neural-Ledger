"""Personal data in bank statement text: deterministic rules that find it, and placeholders that replace it.

A statement is redacted once, at import, before anything is stored, classified, audited or returned
(ADR-028). These rules are the floor: they always run, need no network and are written for Chilean
cartolas. An optional detector (the PersonalDataDetector port) may add spans; nothing removes one.

Kept on purpose, because it is financial data: merchants, employer and payee names
(`REMUNERACION <company>`, `PAGO PROVEEDOR <company>`), `CUOTA nn/NN` (the estimator reads it),
amounts, dates and short store numbers. The bank's document number and branch code are fields of
their own and never pass through here.

Placeholders are stable codes, never text for people: [PERSON] [ID] [NUMBER] [EMAIL] [PHONE] [ADDRESS].
They hold no digit and no '@', so no rule matches them and redacting twice changes nothing.
Clients translate them; the backend never does.

To catch more, extend the word sets below when a real cartola (kept local, in cartolas/) shows a
new pattern; never commit the cartola.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

REDACTION_VERSION = "pii-0.1"  # these rules; every import reports the version that redacted it


class Placeholder(str, Enum):
    """What a masked span held. The value is the stable code (contracts/common/redaction.schema.json)."""

    PERSON = "PERSON"
    ID = "ID"  # a Chilean RUT or RUN with a valid check digit
    NUMBER = "NUMBER"  # account, card and other long numbers
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    ADDRESS = "ADDRESS"  # only a detector finds addresses

    @property
    def tag(self) -> str:
        return f"[{self.value}]"


PLACEHOLDER_CODES: tuple[str, ...] = tuple(p.value for p in Placeholder)

# When spans overlap, the merged span takes the most specific category among them.
_MOST_SPECIFIC_FIRST = (Placeholder.EMAIL, Placeholder.PHONE, Placeholder.ID, Placeholder.ADDRESS, Placeholder.PERSON, Placeholder.NUMBER)
_PRIORITY = {category: rank for rank, category in enumerate(_MOST_SPECIFIC_FIRST)}


@dataclass(frozen=True, slots=True)
class Span:
    """Characters [start, end) of one text that hold personal data of one kind."""

    start: int
    end: int
    category: Placeholder

    def __post_init__(self) -> None:
        if not 0 <= self.start < self.end:
            raise ValueError(f"not a span: [{self.start}, {self.end})")


# ---- the rules -------------------------------------------------------------------------------------

MIN_NUMBER_DIGITS = 7  # account and card numbers, the transfer ids Santander prints; store numbers are shorter

_DASHES = r"\-\N{HYPHEN}-\N{EN DASH}\N{MINUS SIGN}"  # hyphen, and the dashes PDFs and OCR print instead
_EMAIL = re.compile(r"[\w.%+-]+@[\w-]+(?:\.[\w-]+)+")
# 7 or 8 digits, with or without thousands dots, then the check digit, with or without a dash: 11.111.111-1, 111111111
_RUT = re.compile(rf"(?<![\d{_DASHES}])(\d{{1,2}}\.\d{{3}}\.\d{{3}}|\d{{7,8}})(?:\s?[{_DASHES}]\s?)?([\dKk])(?!\w)")
_DIGIT_GROUP = re.compile(r"\d+")
_NUMBER_GAP = re.compile(rf"\s*[{_DASHES}]?\s*")  # what may separate the digit groups of one number

# Chilean numbers have 9 digits after the country code: mobiles 9xxxxxxxx, Santiago 22xxxxxxx, regions <area>xxxxxxx.
_AREA = r"(?:2|3[2-5]|4[1235]|5[123578]|6[13457]|7[1235])"
_SEP = r"[\s.\-]"
_PHONE = re.compile(
    r"(?<![\w+])(?:"
    rf"(?P<cc>\(?\+?\s?56\)?{_SEP}?)(?:\(\d{{1,2}}\)\s?|\d)(?:{_SEP}?\d){{7,8}}"  # +56 9 1234 5678, (+56) (2) 2123 4567
    rf"|9{_SEP}?\d{{4}}{_SEP}?\d{{4}}"  # 9 1234 5678
    rf"|(?:\({_AREA}\)\s?|{_AREA}{_SEP})\d{{3,4}}{_SEP}?\d{{4}}"  # (2) 2123 4567, 41 212 3456
    r")(?!\d)"
)

# Names: the counterparty of a transfer, after TRANSF / TRANSFERENCIA / TEF / TRASPASO and A / DE / DESDE / PARA.
TRANSFER_KEYWORDS = frozenset({"transf", "transferencia", "transferencias", "tef", "traspaso", "traspasos"})
CONNECTORS = frozenset({"a", "al", "de", "del", "desde", "para"})
# Words a bank prints around the counterparty ("TRANSF INTERNET A", "A TERCEROS"). Never a name, so they stay.
TRANSFER_WORDS = frozenset(
    {
        "internet", "electronica", "electronico", "en", "linea", "web", "app", "movil", "otros", "otro", "otras", "otra",
        "banco", "bancos", "terceros", "tercero", "recibida", "recibido", "enviada", "enviado", "inmediata", "entre",
        "cuenta", "cuentas", "cta", "ctas", "mi", "mis", "propia", "propias", "propio", "propios", "misma", "mismo",
    }
)  # fmt: skip
# The user's own accounts and products ("Transf a Ahorro", "Traspaso a Linea de Credito"): own money moving
# (ADR-024), so these words stay too. A word after them is still treated as a possible name.
OWN_ACCOUNT_TERMS = frozenset(
    {
        "ahorro", "ahorros", "vivienda", "corriente", "cte", "vista", "fondo", "fondos", "mutuo", "mutuos", "ffmm",
        "credito", "sobregiro", "tarjeta", "tarjetas", "deposito", "depositos", "plazo", "inversion", "inversiones",
    }
)  # fmt: skip
_NEVER_A_NAME = CONNECTORS | TRANSFER_WORDS | OWN_ACCOUNT_TERMS
_ENDS_A_NAME = frozenset({"cuota", "cuotas"})  # CUOTA nn/NN after a counterparty stays readable for the estimator
_MAX_WORDS_BEFORE_CONNECTOR = 4

_TOKEN = re.compile(r"\S+")
_PLACEHOLDER = re.compile(r"\[(?:" + "|".join(PLACEHOLDER_CODES) + r")\]")
_PUNCTUATION = ".,;:!?()[]{}\"'*#«»“”‘’"


def find_spans(text: str) -> tuple[Span, ...]:
    """Every span the rules find. They may overlap; `apply` merges them."""
    return (*_emails(text), *_ruts(text), *_phones(text), *_long_numbers(text), *_transfer_names(text))


def _emails(text: str) -> list[Span]:
    return [Span(m.start(), m.end(), Placeholder.EMAIL) for m in _EMAIL.finditer(text)]


def check_digit(body: str) -> str:
    """The RUT check digit (módulo 11) of its digits: '11111111' -> '1', '10000013' -> 'K'."""
    total, factor = 0, 2
    for ch in reversed(body):
        total += int(ch) * factor
        factor = 2 if factor == 7 else factor + 1
    rest = 11 - total % 11
    return "0" if rest == 11 else "K" if rest == 10 else str(rest)


def _ruts(text: str) -> list[Span]:
    """A RUT with a valid check digit is an [ID]. One that fails (a typo, an OCR misread) is still masked, as a [NUMBER]."""
    spans = []
    for m in _RUT.finditer(text):
        valid = check_digit(m.group(1).replace(".", "")) == m.group(2).upper()
        spans.append(Span(m.start(), m.end(), Placeholder.ID if valid else Placeholder.NUMBER))
    return spans


def _phones(text: str) -> list[Span]:
    spans = []
    for m in _PHONE.finditer(text):
        digits = [ch for ch in m.group() if ch.isdigit()]
        national = digits[2:] if m.group("cc") is not None else digits
        if len(national) == 9:
            spans.append(Span(m.start(), m.end(), Placeholder.PHONE))
    return spans


def _long_numbers(text: str) -> list[Span]:
    """Runs of 7 or more digits, also when split by spaces or dashes: 0000000003, 4555 1234 5678 9012, 0-000-00-12345-6."""
    spans: list[Span] = []
    run: list[re.Match[str]] = []

    def close() -> None:
        if sum(len(g.group()) for g in run) >= MIN_NUMBER_DIGITS:
            spans.append(Span(run[0].start(), run[-1].end(), Placeholder.NUMBER))
        run.clear()

    for group in _DIGIT_GROUP.finditer(text):
        if run and not _same_number(text, run[-1], group):
            close()
        run.append(group)
    if run:
        close()
    return spans


def _same_number(text: str, left: re.Match[str], right: re.Match[str]) -> bool:
    """Only spaces and one dash between them, and neither is half of a fraction such as CUOTA 03/12."""
    gap = text[left.end() : right.start()]
    return _NUMBER_GAP.fullmatch(gap) is not None and not _in_fraction(text, left) and not _in_fraction(text, right)


def _in_fraction(text: str, group: re.Match[str]) -> bool:
    return text[group.start() - 1 : group.start()] == "/" or text[group.end() : group.end() + 1] == "/"


def _transfer_names(text: str) -> list[Span]:
    """The counterparty of a transfer, up to the first number, address or placeholder after it.

    'Transf a JUAN PEREZ 11.111.111-1' masks JUAN PEREZ; 'Transf a Ahorro' masks nothing.
    """
    tokens = list(_TOKEN.finditer(text))
    spans = []
    i = 0
    while i < len(tokens):
        if _fold(tokens[i].group()) not in TRANSFER_KEYWORDS:
            i += 1
            continue
        j = i + 1  # "TRANSF INTERNET A": a few bank words may come before the connector
        while j < len(tokens) and j - i <= _MAX_WORDS_BEFORE_CONNECTOR and _fold(tokens[j].group()) in TRANSFER_WORDS:
            j += 1
        if j >= len(tokens) or _fold(tokens[j].group()) not in CONNECTORS:
            i += 1
            continue
        first = j + 1
        while first < len(tokens) and _skippable(tokens[first].group()):
            first += 1
        last = first
        while last < len(tokens) and _kind(tokens[last].group()) != "data" and _fold(tokens[last].group()) not in _ENDS_A_NAME:
            last += 1
        while last > first and _kind(tokens[last - 1].group()) == "punctuation":
            last -= 1
        if last > first and not _PLACEHOLDER.search(tokens[first].group()):
            spans.append(_name_span(tokens[first], tokens[last - 1]))
        i = max(last, j + 1)
    return spans


def _kind(token: str) -> str:
    """'data': digits, an address or a placeholder (other rules, or an earlier pass, handle it); else a word or punctuation."""
    if _PLACEHOLDER.search(token) or "@" in token or any(ch.isdigit() for ch in token):
        return "data"
    return "word" if any(ch.isalpha() for ch in token) else "punctuation"


def _skippable(token: str) -> bool:
    """What may stand between the connector and a name. A placeholder is not: it means the name is already masked."""
    if _PLACEHOLDER.search(token):
        return False
    return _kind(token) != "word" or _fold(token) in _NEVER_A_NAME


def _fold(token: str) -> str:
    """Lower case, without accents or surrounding punctuation: 'Línea' -> 'linea', 'TRANSF.' -> 'transf'."""
    plain = "".join(ch for ch in unicodedata.normalize("NFKD", token) if not unicodedata.combining(ch))
    return plain.casefold().strip(_PUNCTUATION)


def _name_span(first: re.Match[str], last: re.Match[str]) -> Span:
    """From the first to the last word, without the punctuation around them, unless the name opened a bracket."""
    text = first.string
    start = first.start() + len(first.group()) - len(first.group().lstrip(_PUNCTUATION))
    end = last.end() - (len(last.group()) - len(last.group().rstrip(_PUNCTUATION)))
    if text[start:end].count("(") > text[start:end].count(")") and text[end : end + 1] == ")":
        end += 1
    return Span(start, end, Placeholder.PERSON)


# ---- applying spans ---------------------------------------------------------------------------------


def merge_spans(spans: Iterable[Span]) -> tuple[Span, ...]:
    """Overlapping or touching spans become one, labelled with the most specific category among them.

    The result covers every character of every input span, so a span can only add masking.
    """
    merged: list[Span] = []
    for span in sorted(spans, key=lambda s: (s.start, s.end)):
        if merged and span.start <= merged[-1].end:
            last = merged[-1]
            category = min(last.category, span.category, key=_PRIORITY.__getitem__)
            merged[-1] = Span(last.start, max(last.end, span.end), category)
        else:
            merged.append(span)
    return tuple(merged)


def apply(text: str, spans: Iterable[Span]) -> str:
    """Replace each span with its placeholder; overlapping spans become one placeholder. Pure: no rule runs here."""
    parts: list[str] = []
    cursor = 0
    for span in merge_spans(spans):
        if span.end > len(text):
            raise ValueError(f"span [{span.start}, {span.end}) is outside a text of {len(text)} characters")
        parts += [text[cursor : span.start], span.category.tag]
        cursor = span.end
    parts.append(text[cursor:])
    return "".join(parts)


def redact_text(text: str) -> str:
    """The rules alone: what a statement line stores when no detector adds anything."""
    return apply(text, find_spans(text))


ACCOUNT_MASK = "****"


def mask_account(account_ref: str) -> str:
    """Keep only the last 4 digits of an account reference: '0-000-00-12345-6' -> '****3456'.

    A reference of 4 digits or fewer would show whole, so it is masked entirely. A masked one stays as it is.
    """
    digits = re.sub(r"\D", "", account_ref)
    if len(digits) > 4 or account_ref.startswith(ACCOUNT_MASK):
        return ACCOUNT_MASK + digits[-4:]
    return ACCOUNT_MASK
