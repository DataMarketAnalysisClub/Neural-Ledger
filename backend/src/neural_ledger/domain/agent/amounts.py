"""Amounts as people write them: one grammar for the verifier and for every check that an amount is the user's.

"$1.200.000", "1,2M", "1,2 palos", "15 lucas", "15 mil": `extract_numbers` reads money and percentages the way the response
verifier checks them (counts, days and years are skipped). `written_amounts` is wider on purpose: every number the
user wrote, so that an amount the copilot proposes can be checked against it (rule 2), never made up by a model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from ..finance.paycycle import payday
from ..memory.catalog import MAX_SALARY_NET
from ..shared.month import Month

_NUMBER = re.compile(
    r"(?P<prefix>(?:CLP|USD|EUR|US\$|CL\$|\$)\s?)?"
    r"(?P<int>\d{1,3}(?:[.,']\d{3})+|\d+)"
    r"(?:[.,](?P<dec>\d{1,2})(?!\d))?"
    r"\s?(?P<suffix>(?:k|K|mil|lucas|luca|MM|M|millones|million|palos|palo)\b)?"
    r"(?P<pct>\s?%)?"
)
_APPROX = re.compile(
    r"(about|around|approx\.?|approximately|roughly|aprox\.?|aproximadamente|cerca de|alrededor de|~)\s*$",
    re.IGNORECASE,
)
_SCALE = {"k": 1_000, "K": 1_000, "mil": 1_000, "lucas": 1_000, "luca": 1_000, "M": 1_000_000, "MM": 1_000_000, "millones": 1_000_000, "million": 1_000_000, "palos": 1_000_000, "palo": 1_000_000}


@dataclass(frozen=True, slots=True)
class Number:
    value: Decimal
    is_percent: bool
    approximate: bool
    text: str


def extract_numbers(text: str) -> list[Number]:
    found: list[Number] = []
    for m in _NUMBER.finditer(text):
        start, end = m.span()
        before = text[start - 1] if start > 0 else ""
        after = text[end] if end < len(text) else ""
        if (before and before in "-/_") or (after and after in "-/_") or before.isalnum():
            continue  # dates (2026-12), ranges, identifiers
        digits = re.sub(r"[.,']", "", m["int"])
        value = Decimal(digits)
        if m["dec"]:
            value += Decimal(m["dec"]) / (Decimal(10) ** len(m["dec"]))
        suffix = m["suffix"]
        if suffix:
            value *= _SCALE[suffix]
        is_percent = bool(m["pct"])
        grouped = any(sep in m["int"] for sep in ".,'")
        if not is_percent and not m["prefix"] and not suffix:
            if value < 1000:
                continue  # counts, days, ratios
            if not grouped and 1900 <= value <= 2100 and not m["dec"]:
                continue  # years
        approximate = bool(_APPROX.search(text[max(0, start - 20) : start])) or bool(suffix)
        found.append(Number(value, is_percent, approximate, m.group(0).strip()))
    return found


def written_amounts(text: str) -> frozenset[int]:
    """Every amount the user wrote: "15 lucas", "15 mil", "$15.000", "15000", "800". Used to check that an amount
    the copilot proposes is one the user said (rule 2), never one the model made up."""
    joined = re.sub(r"(\d)[.,](\d{3})(?!\d)", r"\1\2", text)
    while joined != (again := re.sub(r"(\d)[.,](\d{3})(?!\d)", r"\1\2", joined)):
        joined = again
    plain = {int(n) for n in re.findall(r"\d+", joined) if len(n) <= 9}
    return frozenset(plain | {int(n.value) for n in extract_numbers(text) if not n.is_percent and n.value == int(n.value)})


# ---- a salary said in chat (ADR-048) --------------------------------------------------------------------------


_MONTHS = {
    "enero": 1, "january": 1, "febrero": 2, "february": 2, "marzo": 3, "march": 3, "abril": 4, "april": 4,
    "mayo": 5, "may": 5, "junio": 6, "june": 6, "julio": 7, "july": 7, "agosto": 8, "august": 8,
    "septiembre": 9, "setiembre": 9, "september": 9, "octubre": 10, "october": 10,
    "noviembre": 11, "november": 11, "diciembre": 12, "december": 12,
}
_FROM = r"(?:desde|a partir de|from|starting(?: in| from)?|since|beginning(?: in)?)"
_YEAR = r"(?:\s*,?\s*(?:de |del |of )?(?P<year>(?:19|20|21)\d{2})(?!\d))?"
_NAMED = re.compile(
    r"(?P<from>\b" + _FROM + r"\s+(?:(?:el |la |the )?(?:mes de |month of )?))?"
    r"(?P<prep>\b(?:en|in|de|del|para|for|of)\s+)?"
    r"\b(?P<name>" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\b" + _YEAR,
    re.IGNORECASE,
)
_NUMERIC = re.compile(r"(?P<from>\b" + _FROM + r"\s+)?(?<![\d/-])(?:(?P<y1>(?:19|20|21)\d{2})-(?P<m1>0[1-9]|1[0-2])|(?P<m2>0?[1-9]|1[0-2])/(?P<y2>(?:19|20|21)\d{2}))(?![\d/-])", re.I)


@dataclass(frozen=True, slots=True)
class IncomeStatement:
    """What a message says about a salary: amounts in the order written, and the pay month it starts in.

    `read_as` says how the month was read, for the card to show: explicit_year (month and year written),
    next_occurrence (a month without a year: its next occurrence, the current month included, never retroactive) or
    next_payday (no month written: the month of the next payday). The model never picks among the candidates.
    """

    candidates: tuple[int, ...]
    pay_month: Month
    read_as: str


def parse_income_statement(text: str, today: date) -> IncomeStatement:
    """Read the user's current message only: never earlier messages, never anything a model wrote."""
    candidates: list[int] = []
    for n in extract_numbers(text):
        if n.is_percent or n.value != int(n.value) or not 1 <= n.value <= MAX_SALARY_NET:
            continue
        if int(n.value) not in candidates:
            candidates.append(int(n.value))
    return IncomeStatement(tuple(candidates), *_pay_month(text, today))


def _pay_month(text: str, today: date) -> tuple[Month, str]:
    mentions: list[tuple[bool, int, int, int | None]] = []  # (after "desde", position, month, year)
    for m in _NUMERIC.finditer(text):
        year, month = (m["y1"], m["m1"]) if m["y1"] else (m["y2"], m["m2"])
        mentions.append((bool(m["from"]), m.start(), int(month), int(year)))
    for m in _NAMED.finditer(text):
        name = m["name"].lower()
        if name == "may" and not (m["from"] or m["prep"] or m["year"]):
            continue  # "may I…": the English month only after a preposition or before a year
        mentions.append((bool(m["from"]), m.start(), _MONTHS[name], int(m["year"]) if m["year"] else None))
    if mentions:
        _, _, month, year = min(mentions, key=lambda x: (not x[0], x[1]))  # a month after "desde" wins, then the first
        if year is not None:
            return Month(year, month), "explicit_year"
        return Month(today.year if month >= today.month else today.year + 1, month), "next_occurrence"
    current = Month.of(today)
    return (current if today <= payday(current) else current.plus(1)), "next_payday"
