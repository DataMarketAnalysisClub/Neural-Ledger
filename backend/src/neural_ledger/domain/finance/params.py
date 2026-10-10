"""Parameter register (Financial Core design, section 5).

Changing any value after the freeze means a new `version`; the audit log records which
version produced each decision. Values marked (A+E) need confirmation by Roles A and E.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, fields
from decimal import Decimal
from fractions import Fraction

from .profile import RiskProfile


@dataclass(frozen=True, slots=True)
class FinanceParams:
    version: str
    liquidity_floor: int  # checked at each pay-cycle trough (A+E)
    conservative_income_percentile: int  # freelancers (A+E)
    variable_spend_percentile: int
    spend_window_months: int
    seasonal_months: tuple[int, ...]
    seasonal_factor_min: Fraction
    seasonal_factor_max: Fraction
    stress_shock_min: int  # (A+E)
    dashboard_horizon_months: int
    check_horizon_months: int  # plan and purchase checks (extends to the last cuota)
    plan_window_months: int  # rule sized on the lowest Available in [s, s + window - 1]
    reserve_min_months: int  # trigger for hard rule H1 (A+E)
    reserve_target_months: int  # (A+E)
    reserve_rebuild_months: int
    near_term_goal_months: int  # same line as hard rule H3
    profile_share: tuple[Fraction, Fraction, Fraction]  # conservative, moderate, aggressive
    rule_rounding: int  # savings rules are rounded down to this step
    approx_rounding: int  # "about" amounts (largest affordable purchase) are rounded down to this step
    allowed_installments: tuple[int, ...]
    default_monthly_rate: Decimal  # used only when the offer gives none; always flagged (A+E)
    max_purchase_amount: int
    alternative_defer_max_months: int
    max_alternatives: int
    min_history_months: int
    recurring_min_hits: int
    recurring_lookback_months: int
    recurring_interval_days: tuple[int, int]
    recurring_amount_tolerance: Fraction
    commitment_confidence_cutoff: Fraction
    recurring_end_days: int  # no occurrence for this many days before as_of -> the item has ended
    installment_parsed_confidence: Fraction  # "CUOTA nn/NN" parsed from text instead of structured metadata
    income_cv_ddof: int  # 1 = sample standard deviation (more conservative than population with 12 points)
    essential_categories: frozenset[str]  # spend categories counted as essentials (section 4.7)
    # Capacity bands (section 4.7). "up" factors: higher is better; "down" factors: lower is better.
    reserve_coverage_bands: tuple[Fraction, Fraction]  # up: low < a <= medium < b <= high
    income_cv_bands: tuple[Fraction, Fraction]  # down: high < a <= medium <= b < low
    debt_service_bands: tuple[Fraction, Fraction]  # down
    headroom_ratio_bands: tuple[Fraction, Fraction]  # up
    stress_coverage_bands: tuple[Fraction, Fraction]  # up

    def share_for(self, profile: RiskProfile) -> Fraction:
        return self.profile_share[profile.rank]

    def fingerprint(self) -> str:
        """Hash of every value except `version`, serialized exactly (Fraction as n/d, Decimal as text).

        tests/unit/test_params_lock.py pins it per version: changing a value without bumping
        `version` fails the build, so the audit log's policy_version always names the numbers used.
        """
        values = {f.name: _exact(getattr(self, f.name)) for f in fields(self) if f.name != "version"}
        return hashlib.sha256(json.dumps(values, sort_keys=True).encode("utf-8")).hexdigest()


def _exact(value: object) -> object:
    if isinstance(value, Fraction):
        return f"{value.numerator}/{value.denominator}"
    if isinstance(value, Decimal):
        return f"decimal:{value}"
    if isinstance(value, (frozenset, set)):
        return sorted(_exact(v) for v in value)
    if isinstance(value, (tuple, list)):
        return [_exact(v) for v in value]
    if isinstance(value, (int, str)) and not isinstance(value, bool):
        return value
    raise TypeError(f"unsupported parameter type {type(value).__name__}")


FC_0_1 = FinanceParams(
    version="fc-0.1",
    liquidity_floor=150_000,
    conservative_income_percentile=20,
    variable_spend_percentile=80,
    spend_window_months=12,
    seasonal_months=(12,),
    seasonal_factor_min=Fraction(1),
    seasonal_factor_max=Fraction(2),
    stress_shock_min=300_000,
    dashboard_horizon_months=6,
    check_horizon_months=12,
    plan_window_months=6,
    reserve_min_months=1,
    reserve_target_months=3,
    reserve_rebuild_months=24,
    near_term_goal_months=12,
    profile_share=(Fraction(2, 5), Fraction(3, 5), Fraction(4, 5)),
    rule_rounding=10_000,
    approx_rounding=1_000,
    allowed_installments=(3, 6, 12, 18, 24),
    default_monthly_rate=Decimal("0.025"),
    max_purchase_amount=100_000_000,
    alternative_defer_max_months=6,
    max_alternatives=3,
    min_history_months=6,
    recurring_min_hits=3,
    recurring_lookback_months=6,
    recurring_interval_days=(28, 35),
    recurring_amount_tolerance=Fraction(5, 100),
    commitment_confidence_cutoff=Fraction(8, 10),
    recurring_end_days=45,
    installment_parsed_confidence=Fraction(9, 10),
    income_cv_ddof=1,
    essential_categories=frozenset({"groceries", "transport", "utilities", "health"}),
    reserve_coverage_bands=(Fraction(1), Fraction(3)),
    income_cv_bands=(Fraction(10, 100), Fraction(25, 100)),
    debt_service_bands=(Fraction(20, 100), Fraction(35, 100)),
    headroom_ratio_bands=(Fraction(25, 100), Fraction(1)),
    stress_coverage_bands=(Fraction(1, 2), Fraction(1)),
)
