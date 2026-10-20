"""The estimated financial model: output of stage 1 (estimation), input of stage 2 (projection).

Stage 1 (ledger -> model) is Role A's estimators in `estimation.py`.
Stage 2 (model -> forecast, surplus, plan, capacity) is pure arithmetic in the other modules.
Persona fixtures are expressed at this level, so the calibration targets are the contract
between Role E's generator and Role A's estimators.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from fractions import Fraction

from ..ledger.entities import Goal, IncomeType
from ..shared.month import Month
from ..shared.numbers import round_half_up


class Scenario(str, Enum):
    TYPICAL = "typical"
    CONSERVATIVE = "conservative"
    STRESS = "stress"


class CommitmentType(str, Enum):
    INSTALLMENT = "installment"
    RENT = "rent"
    SUBSCRIPTION = "subscription"
    LOAN = "loan"


DEBT_TYPES = frozenset({CommitmentType.INSTALLMENT, CommitmentType.LOAN})


@dataclass(frozen=True, slots=True)
class Commitment:
    commitment_id: str
    type: CommitmentType
    label: str  # may come from merchant text: treat as untrusted data
    amount: int
    first_due: Month
    last_due: Month | None  # None = open-ended (rent, subscriptions)
    confidence: float = 1.0
    installments_total: int | None = None
    evidence_txn_ids: tuple[str, ...] = ()

    @property
    def is_debt(self) -> bool:
        return self.type in DEBT_TYPES

    def due_in(self, month: Month) -> bool:
        return self.first_due <= month and (self.last_due is None or month <= self.last_due)


@dataclass(frozen=True, slots=True)
class IncomeStep:
    """Income from a projected cycle on, until the next step (ADR-049 §8)."""

    start: Month
    typical: int
    conservative: int


@dataclass(frozen=True, slots=True)
class IncomeModel:
    type: IncomeType
    typical: int  # contracted net or P50: what was observed
    conservative: int  # contracted net (lower of contract and recent credits) or P20: what was observed
    cv: Fraction  # coefficient of variation of monthly income, always the observed one
    method: str  # "contracted" | "percentile"
    # Per-cycle income where a declared salary applies (ADR-049), in start order; empty = the observed income in
    # every cycle. A step lasts until the next one, so the calendar covers any horizon, a credit's full term included.
    monthly: tuple[IncomeStep, ...] = ()

    def __post_init__(self) -> None:
        starts = [step.start for step in self.monthly]
        if starts != sorted(set(starts)):
            raise ValueError("income steps must have increasing, distinct starts")

    def for_month(self, scenario: Scenario, month: Month) -> int:
        """The income of one projected cycle; stress uses the conservative income (its shock is separate)."""
        typical, conservative = self.typical, self.conservative
        for step in self.monthly:
            if step.start > month:
                break
            typical, conservative = step.typical, step.conservative
        return typical if scenario is Scenario.TYPICAL else conservative


@dataclass(frozen=True, slots=True)
class CategorySpend:
    category: str
    p50: int
    p80: int
    essential: bool


@dataclass(frozen=True, slots=True)
class SpendModel:
    categories: tuple[CategorySpend, ...]
    seasonal_factors: Mapping[int, Fraction] = field(default_factory=dict)  # month number -> factor
    window_months: int = 12

    def factor(self, month: Month) -> Fraction:
        return self.seasonal_factors.get(month.month, Fraction(1))

    def total(self, month: Month, quantile: str) -> int:
        """Category quantiles summed, seasonal factor applied exactly, rounded once."""
        if quantile not in ("p50", "p80"):
            raise ValueError(f"unknown quantile {quantile!r}")
        base = sum(getattr(c, quantile) for c in self.categories)
        return round_half_up(base * self.factor(month))

    def essentials_p80(self) -> int:
        """Essential categories at P80, without seasonality (matches golden E05)."""
        return sum(c.p80 for c in self.categories if c.essential)


@dataclass(frozen=True, slots=True)
class Balances:
    checking: int  # opening trough: balance just before the first projected payday
    reserve: int
    goal_buckets: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class FinancialModel:
    user_id: str
    currency: str
    as_of: date
    first_cycle: Month  # first pay cycle to project
    balances: Balances
    income: IncomeModel
    commitments: tuple[Commitment, ...]
    spend: SpendModel
    goals: tuple[Goal, ...]
    source_version: str  # ledger version or fixture hash: part of every snapshot id
    largest_one_off_expense: int = 0

    def commitments_due(self, month: Month, types: frozenset[CommitmentType] | None = None) -> int:
        return sum(
            c.amount for c in self.commitments if c.due_in(month) and (types is None or c.type in types)
        )

    def debt_service_due(self, month: Month) -> int:
        return self.commitments_due(month, DEBT_TYPES)

    def missing_fields(self) -> tuple[str, ...]:
        """Hard rule H4: unknown state is a result, not a guess."""
        missing: list[str] = []
        if self.income.conservative <= 0 and self.income.typical <= 0:
            missing.append("income")
        if not self.spend.categories:
            missing.append("spend.categories")
        if self.spend.window_months < 6:
            missing.append("spend.history (at least 6 months)")
        return tuple(missing)
