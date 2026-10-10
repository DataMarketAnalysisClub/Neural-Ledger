"""Risk profiles and the permitted-profile rule: permitted = min(tolerance, capacity) + hard rules."""

from __future__ import annotations

from enum import Enum


class RiskProfile(str, Enum):
    CONSERVATIVE = "conservative"
    MODERATE = "moderate"
    AGGRESSIVE = "aggressive"

    @property
    def rank(self) -> int:
        return _RANK[self]

    @classmethod
    def parse(cls, text: str) -> RiskProfile:
        try:
            return cls(text.strip().lower())
        except ValueError as exc:
            raise ValueError(f"unknown risk profile {text!r}") from exc


_RANK = {RiskProfile.CONSERVATIVE: 0, RiskProfile.MODERATE: 1, RiskProfile.AGGRESSIVE: 2}


def lower_profile(a: RiskProfile, b: RiskProfile) -> RiskProfile:
    return a if a.rank <= b.rank else b
