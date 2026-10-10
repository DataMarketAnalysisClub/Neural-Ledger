"""Installment (cuota) cost: c = P * r / (1 - (1 + r)^-n), or P / n when r = 0.

Decision taken here (flagged in docs/SCOPE.md, issue F2): all cuotas are equal and
total cost = n * c, which matches golden E02 (467,940). The Financial Core text says
"the last cuota absorbs the remainder" (that would give 467,938); Role A decides.
Nothing is labelled "CAE" until the Chilean legal definition is checked.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

_ONE = Decimal(1)


@dataclass(frozen=True, slots=True)
class InstallmentQuote:
    principal: int
    installments: int
    monthly_rate: Decimal
    rate_assumed: bool
    installment: int
    total_cost: int
    total_interest: int
    effective_annual_rate: Decimal  # (1 + r)^12 - 1


def payment_factor(rate: Decimal, installments: int) -> Decimal:
    if installments < 1:
        raise ValueError("installments must be at least 1")
    if rate == 0:
        return _ONE / Decimal(installments)
    return rate / (_ONE - (_ONE + rate) ** (-installments))


def quote(principal: int, installments: int, monthly_rate: Decimal, *, rate_assumed: bool) -> InstallmentQuote:
    raw = Decimal(principal) * payment_factor(monthly_rate, installments)
    installment = int(raw.quantize(_ONE, rounding=ROUND_HALF_UP))
    total = installment * installments
    effective = (_ONE + monthly_rate) ** 12 - _ONE
    return InstallmentQuote(
        principal=principal,
        installments=installments,
        monthly_rate=monthly_rate,
        rate_assumed=rate_assumed,
        installment=installment,
        total_cost=total,
        total_interest=total - principal,
        effective_annual_rate=effective,
    )


def max_principal(installment_cap: int, installments: int, monthly_rate: Decimal) -> int:
    """Largest principal whose cuota does not exceed `installment_cap`."""
    if installment_cap <= 0:
        return 0
    value = Decimal(installment_cap) / payment_factor(monthly_rate, installments)
    return int(value.to_integral_value(rounding=ROUND_FLOOR))


def percent(value: Decimal, places: int = 1) -> float:
    """0.344888 -> 34.5"""
    quantum = Decimal(1).scaleb(-places)
    return float((value * 100).quantize(quantum, rounding=ROUND_HALF_UP))
