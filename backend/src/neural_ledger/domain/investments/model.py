"""Investments the user holds at another institution, read-only (Fintual first, ADR-044).

The provider reports goals ("metas") with their current value and, when it reports them, the net amount the user
deposited. Neural Ledger never moves money there and never recommends an instrument: it describes what the
provider reported and computes totals and gains in integers. Amounts arrive as exact decimals and become integer
minor units here, rounded half up once. Goal names are the user's own labels at the provider: third-party text,
wrapped as untrusted before any model sees it (S30).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from ..agent.untrusted import sanitize
from ..shared.envelope import Caveat, Fact
from ..shared.errors import InvalidInput
from ..shared.hashing import content_id
from ..shared.numbers import round_half_up

INVESTMENTS_VERSION = "inv-0.1"
PROVIDERS = {"fintual": "Fintual"}  # provider id -> the name people know it by, as the agent must say it
CURRENCIES = ("CLP",)  # the provider reports goal values in pesos
MAX_GOALS = 50
MAX_AMOUNT = 10**12  # minor units: a bound on what a provider can make us store, like the estimator's ledger limit
MAX_SNAPSHOTS = 400  # syncs kept per user (about a year of daily ones); older ones are dropped
STALE_AFTER = timedelta(hours=24)

_GOAL_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


@dataclass(frozen=True, slots=True)
class ReportedGoal:
    """A goal as the provider reported it, before validation. Amounts are exact decimals in the account's currency."""

    goal_id: str
    name: str
    value: Decimal
    deposited: Decimal | None = None


@dataclass(frozen=True, slots=True)
class InvestmentGoal:
    goal_id: str
    name: str  # the user's label at the provider: untrusted text, control characters removed
    value: int  # current value, minor units
    deposited: int | None = None  # net deposits (deposits less withdrawals), when the provider reports them

    @property
    def gain(self) -> int | None:
        return None if self.deposited is None else self.value - self.deposited


@dataclass(frozen=True, slots=True)
class InvestmentSnapshot:
    """Every goal of the linked account as one sync read it. Synthetic when it came from the offline adapter."""

    user_id: str
    provider: str
    currency: str
    fetched_at: datetime
    goals: tuple[InvestmentGoal, ...]
    synthetic: bool = False

    @property
    def snapshot_id(self) -> str:
        return content_id("inv", self.user_id, self.provider, self.currency, self.fetched_at, self.goals, self.synthetic)

    @property
    def total_value(self) -> int:
        return sum(goal.value for goal in self.goals)

    @property
    def total_deposited(self) -> int | None:
        """Only when every goal reports its deposits: a partial sum would understate them and overstate the gain."""
        deposits = [goal.deposited for goal in self.goals]
        if not deposits or any(d is None for d in deposits):
            return None
        return sum(d for d in deposits if d is not None)

    @property
    def total_gain(self) -> int | None:
        deposited = self.total_deposited
        return None if deposited is None else self.total_value - deposited

    def is_stale(self, now: datetime) -> bool:
        return now - self.fetched_at > STALE_AFTER


@dataclass(frozen=True, slots=True)
class InvestmentLink:
    """A user's link to an account at a provider. The access token reads that account: it is sealed at rest, never
    logged, never returned by the API and never shown to a model (S31). The repr hides it and the email.

    `adapter` names what created the token (the real API or the offline fixture), so a token is only ever sent
    back to the adapter that issued it. `expired` is set when the provider stops accepting the token."""

    user_id: str
    provider: str
    adapter: str
    email: str = field(repr=False)
    token: str = field(repr=False)
    linked_at: datetime
    expired: bool = False


def snapshot_from_report(
    user_id: str,
    provider: str,
    currency: str,
    fetched_at: datetime,
    reported: Sequence[ReportedGoal],
    *,
    synthetic: bool = False,
) -> InvestmentSnapshot:
    """Validate what the provider reported and turn its amounts into integer minor units. Raises InvalidInput."""
    if provider not in PROVIDERS:
        raise InvalidInput("provider", "unknown investment provider", tuple(PROVIDERS))
    if currency not in CURRENCIES:
        raise InvalidInput("currency", "unsupported currency for an investment account", CURRENCIES)
    if fetched_at.tzinfo is None:
        raise InvalidInput("fetched_at", "the sync time must carry a time zone")
    if len(reported) > MAX_GOALS:
        raise InvalidInput("goals", f"at most {MAX_GOALS} goals per account")
    seen: set[str] = set()
    goals: list[InvestmentGoal] = []
    for i, goal in enumerate(reported):
        if not isinstance(goal.goal_id, str) or not _GOAL_ID.fullmatch(goal.goal_id) or goal.goal_id in seen:
            raise InvalidInput(f"goals[{i}].goal_id", "goal ids are unique, 1-64 letters, digits, _ or -")
        seen.add(goal.goal_id)
        if not isinstance(goal.name, str):
            raise InvalidInput(f"goals[{i}].name", "a goal name is text")
        value = _amount(goal.value, f"goals[{i}].value", minimum=0)
        deposited = None if goal.deposited is None else _amount(goal.deposited, f"goals[{i}].deposited", minimum=-MAX_AMOUNT)
        goals.append(InvestmentGoal(goal.goal_id, sanitize(goal.name), value, deposited))
    return InvestmentSnapshot(user_id, provider, currency, fetched_at, tuple(goals), synthetic)


def _amount(value: Decimal | int, field_name: str, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (Decimal, int)) or (isinstance(value, Decimal) and not value.is_finite()):
        raise InvalidInput(field_name, "an amount is a finite number")
    rounded = round_half_up(Decimal(value))
    if not minimum <= rounded <= MAX_AMOUNT:
        raise InvalidInput(field_name, f"an amount is between {minimum} and {MAX_AMOUNT}")
    return rounded


def mask_email(email: str) -> str:
    """What the account owner sees of the linked address: its first character and its domain."""
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}" if local and domain else "***"


def overview_facts(snapshot: InvestmentSnapshot) -> tuple[Fact, ...]:
    """Every number the agent may say about the account. Values are the provider's; totals and gains are ours."""
    name = PROVIDERS[snapshot.provider]
    on = snapshot.fetched_at.date().isoformat()
    cur = snapshot.currency
    facts = [
        Fact("investments.goals", len(snapshot.goals), "count", f"goals in the linked {name} account"),
        Fact("investments.total_value", snapshot.total_value, cur, f"sum of the goal values {name} reported on {on}"),
    ]
    if snapshot.total_deposited is not None and snapshot.total_gain is not None:
        facts.append(Fact("investments.total_deposited", snapshot.total_deposited, cur, f"sum of the net deposits {name} reported on {on}"))
        facts.append(Fact("investments.total_gain", snapshot.total_gain, cur, "total value less total net deposits"))
    for goal in snapshot.goals:
        facts.append(Fact(f"investments.goal.{goal.goal_id}.value", goal.value, cur, f"goal value {name} reported on {on}"))
        if goal.deposited is not None and goal.gain is not None:
            facts.append(Fact(f"investments.goal.{goal.goal_id}.deposited", goal.deposited, cur, f"net deposits {name} reported on {on}"))
            facts.append(Fact(f"investments.goal.{goal.goal_id}.gain", goal.gain, cur, "goal value less its net deposits"))
    return tuple(facts)


def overview_caveats(snapshot: InvestmentSnapshot, now: datetime) -> tuple[Caveat, ...]:
    """What the agent must say with those numbers. Never a forecast and never advice: these describe the past."""
    name = PROVIDERS[snapshot.provider]
    caveats = [
        Caveat(
            "INVESTMENTS_AS_REPORTED",
            f"These figures are as {name} reported them at the last sync; they change every day, and past gains do not predict future ones.",
            (name,),
        )
    ]
    if snapshot.synthetic:
        caveats.append(Caveat("INVESTMENTS_SYNTHETIC", "They are synthetic sandbox figures, not a real account.", ("synthetic", "sintétic", "sandbox")))
    if snapshot.is_stale(now):
        caveats.append(
            Caveat("INVESTMENTS_STALE", "The last sync was more than a day ago; sync again in the app for current values.", ("sync", "sincroniz", "actualiz"))
        )
    return tuple(caveats)
