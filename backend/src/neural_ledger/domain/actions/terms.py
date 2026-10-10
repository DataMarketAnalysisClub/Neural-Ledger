"""Confirmation contract (Spec v0 section 5).

The UI shows exactly these terms; execution must match them exactly. The amount comes from
the stored plan snapshot, never from model text. After the user confirms, the system creates
an Authorization bound to a signed hash of the canonical terms, with an expiry and single use.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime
from enum import Enum
from typing import Any

from ..finance.plan import SavingsPlan
from ..shared.errors import InvalidInput
from ..shared.hashing import canonical_json


class ActionType(str, Enum):
    CREATE_SAVINGS_RULE = "create_savings_rule"


class Frequency(str, Enum):
    MONTHLY = "monthly"


@dataclass(frozen=True, slots=True)
class ActionTerms:
    action: ActionType
    amount: int
    currency: str
    frequency: Frequency
    source_account: str
    destination: str
    effective_date: date

    def __post_init__(self) -> None:
        if isinstance(self.amount, bool) or not isinstance(self.amount, int) or self.amount <= 0:
            raise InvalidInput("amount", "amount must be a positive integer in minor units")
        if len(self.currency) != 3 or not self.currency.isupper():
            raise InvalidInput("currency", "currency must be an ISO 4217 code")

    def canonical(self) -> str:
        return canonical_json(self)

    def with_amount(self, amount: int) -> ActionTerms:
        return replace(self, amount=amount)

    @staticmethod
    def from_primitive(data: Mapping[str, Any]) -> ActionTerms:
        try:
            return ActionTerms(
                action=ActionType(data["action"]),
                amount=data["amount"],
                currency=str(data["currency"]),
                frequency=Frequency(data["frequency"]),
                source_account=str(data["source_account"]),
                destination=str(data["destination"]),
                effective_date=date.fromisoformat(str(data["effective_date"])),
            )
        except KeyError as exc:
            raise InvalidInput(str(exc.args[0]), "missing field in action terms") from exc
        except (TypeError, ValueError) as exc:
            raise InvalidInput("terms", f"malformed action terms: {exc}") from exc


class ProposalStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"


@dataclass(frozen=True, slots=True)
class Proposal:
    proposal_id: str
    session_id: str
    user_id: str
    terms: ActionTerms
    source_snapshot_id: str
    created_at: datetime
    expires_at: datetime
    status: ProposalStatus = ProposalStatus.PENDING


@dataclass(frozen=True, slots=True)
class Authorization:
    authorization_id: str
    proposal_id: str
    session_id: str
    user_id: str
    terms: ActionTerms
    action_hash: str  # signature over terms.canonical(); the secret never leaves the Signer
    created_at: datetime
    expires_at: datetime
    consumed_at: datetime | None = None

    def is_expired(self, now: datetime) -> bool:
        return now >= self.expires_at


@dataclass(frozen=True, slots=True)
class SavingsRule:
    rule_id: str
    user_id: str
    amount: int
    currency: str
    frequency: Frequency
    source_account: str
    destination: str
    effective_date: date
    authorization_id: str


@dataclass(frozen=True, slots=True)
class ExecutionReceipt:
    execution_id: str
    ok: bool
    reference: str | None = None
    error: str | None = None


def terms_from_plan(plan: SavingsPlan, currency: str) -> ActionTerms:
    if plan.amount <= 0 or plan.start_month is None:
        raise InvalidInput("plan_snapshot_id", "the plan has no recurring rule to propose (hard rule H2)")
    return ActionTerms(
        action=ActionType.CREATE_SAVINGS_RULE,
        amount=plan.amount,
        currency=currency,
        frequency=Frequency.MONTHLY,
        source_account="checking",
        destination="sandbox_savings",
        effective_date=plan.start_month.first_day(),
    )
