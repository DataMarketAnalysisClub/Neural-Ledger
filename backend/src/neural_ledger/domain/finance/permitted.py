"""Permitted profile = min(tolerance, capacity) plus hard rules (Financial Core 4.8)."""

from __future__ import annotations

from dataclasses import dataclass

from ..shared.envelope import Fact
from .capacity import CapacityAssessment
from .model import FinancialModel
from .plan import H1
from .profile import RiskProfile, lower_profile


@dataclass(frozen=True, slots=True)
class PermittedProfile:
    permitted: RiskProfile
    tolerance: RiskProfile
    capacity: RiskProfile
    hard_rules_triggered: tuple[str, ...]


def derive_permitted_profile(
    tolerance: RiskProfile, capacity: CapacityAssessment, model: FinancialModel
) -> PermittedProfile:
    rules = (H1,) if model.balances.reserve < capacity.reserve_minimum else ()
    return PermittedProfile(lower_profile(tolerance, capacity.level), tolerance, capacity.level, rules)


def permitted_facts(p: PermittedProfile) -> tuple[Fact, ...]:
    return (
        Fact("profile.permitted", p.permitted.value, "profile", "min(tolerance, capacity)"),
        Fact("profile.tolerance", p.tolerance.value, "profile", "questionnaire and language signals"),
        Fact("profile.capacity", p.capacity.value, "profile", "capacity engine"),
    )
