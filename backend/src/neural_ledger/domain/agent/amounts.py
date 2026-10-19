"""Amounts as people write them: one grammar for the verifier and for every check that an amount is the user's.

"$1.200.000", "1,2M", "1,2 palos", "15 lucas", "15 mil": `extract_numbers` reads money and percentages the way the response
verifier checks them (counts, days and years are skipped). `written_amounts` is wider on purpose: every number the
user wrote, so that an amount the copilot proposes can be checked against it (rule 2), never made up by a model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

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
