"""Exact rounding helpers. Money is integer minor units; ratios stay exact until the last step."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction


def round_half_up(value: Fraction | Decimal | int) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, Fraction):
        value = Decimal(value.numerator) / Decimal(value.denominator)
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def floor_to(value: Fraction | int, step: int) -> int:
    """Round down to a multiple of `step` (e.g. savings rules to the nearest 10,000)."""
    if step <= 0:
        raise ValueError("step must be positive")
    whole = value.numerator // value.denominator if isinstance(value, Fraction) else value
    return (whole // step) * step


def ceil_div(numerator: int, denominator: int) -> int:
    return -(-numerator // denominator)
