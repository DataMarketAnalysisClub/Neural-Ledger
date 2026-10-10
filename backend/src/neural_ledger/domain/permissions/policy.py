"""Permission tiers and the deterministic gate (Spec v0 section 4).

Rule: no model (LLM or decision model) can promote an action between tiers.
Only this code authorizes. Every block has a reason and is audited by the caller.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from ..actions.terms import ActionTerms, ActionType, Authorization


class Tier(str, Enum):
    T0 = "T0"  # read financial state
    T1 = "T1"  # analyze and suggest
    T2 = "T2"  # execute an approved sandbox action
    T3 = "T3"  # prohibited, always blocked and logged

    @property
    def rank(self) -> int:
        return int(self.value[1])


class BlockReason(str, Enum):
    UNKNOWN_TOOL = "UNKNOWN_TOOL"
    NEW_BENEFICIARY = "NEW_BENEFICIARY"
    UNKNOWN_DESTINATION = "UNKNOWN_DESTINATION"
    LIMIT_CHANGE = "LIMIT_CHANGE"
    CREDENTIAL_CHANGE = "CREDENTIAL_CHANGE"
    POLICY_OVERRIDE = "POLICY_OVERRIDE"
    SELF_ESCALATION = "SELF_ESCALATION"
    TIER_NOT_ALLOWED = "TIER_NOT_ALLOWED"
    INJECTION_SUSPECTED = "INJECTION_SUSPECTED"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    AUTHORIZATION_NOT_FOUND = "AUTHORIZATION_NOT_FOUND"
    AUTHORIZATION_EXPIRED = "AUTHORIZATION_EXPIRED"
    AUTHORIZATION_REPLAYED = "AUTHORIZATION_REPLAYED"
    AUTHORIZATION_TAMPERED = "AUTHORIZATION_TAMPERED"
    AUTHORIZATION_MISMATCH = "AUTHORIZATION_MISMATCH"
    WRONG_OWNER = "WRONG_OWNER"
    ACTION_NOT_ALLOWED = "ACTION_NOT_ALLOWED"
    UNKNOWN_SOURCE = "UNKNOWN_SOURCE"
    AMOUNT_OVER_LIMIT = "AMOUNT_OVER_LIMIT"
    PROPOSAL_NOT_FOUND = "PROPOSAL_NOT_FOUND"
    PROPOSAL_EXPIRED = "PROPOSAL_EXPIRED"
    PROPOSAL_NOT_PENDING = "PROPOSAL_NOT_PENDING"
    TERMS_CHANGED = "TERMS_CHANGED"
    AUDIT_UNAVAILABLE = "AUDIT_UNAVAILABLE"


# Capabilities the agent must never have. Calls with these names are recognized and logged as T3.
PROHIBITED_CAPABILITIES: dict[str, BlockReason] = {
    "add_beneficiary": BlockReason.NEW_BENEFICIARY,
    "transfer_funds": BlockReason.UNKNOWN_DESTINATION,
    "transfer_to_external": BlockReason.UNKNOWN_DESTINATION,
    "change_transfer_limit": BlockReason.LIMIT_CHANGE,
    "change_credentials": BlockReason.CREDENTIAL_CHANGE,
    "override_policy": BlockReason.POLICY_OVERRIDE,
    "grant_permission": BlockReason.SELF_ESCALATION,
    "confirm_action": BlockReason.SELF_ESCALATION,
}


@dataclass(frozen=True, slots=True)
class PermissionPolicy:
    version: str
    allowed_actions: frozenset[ActionType]
    allowed_sources: frozenset[str]
    allowed_destinations: frozenset[str]
    max_amount_per_action: int
    proposal_ttl_seconds: int
    authorization_ttl_seconds: int


PP_0_1 = PermissionPolicy(
    version="pp-0.1",
    allowed_actions=frozenset({ActionType.CREATE_SAVINGS_RULE}),
    allowed_sources=frozenset({"checking"}),
    allowed_destinations=frozenset({"sandbox_savings"}),
    max_amount_per_action=1_000_000,
    proposal_ttl_seconds=30 * 60,
    authorization_ttl_seconds=10 * 60,
)


@dataclass(frozen=True, slots=True)
class GateDecision:
    allowed: bool
    tier: Tier
    reason: BlockReason | None = None
    detail: str = ""


def _block(reason: BlockReason, detail: str, tier: Tier = Tier.T2) -> GateDecision:
    return GateDecision(False, tier, reason, detail)


def check_terms(terms: ActionTerms, policy: PermissionPolicy) -> GateDecision:
    if terms.action not in policy.allowed_actions:
        return _block(BlockReason.ACTION_NOT_ALLOWED, f"action {terms.action.value} is not allowed", Tier.T3)
    if terms.source_account not in policy.allowed_sources:
        return _block(BlockReason.UNKNOWN_SOURCE, f"source {terms.source_account!r} is not allowed", Tier.T3)
    if terms.destination not in policy.allowed_destinations:
        return _block(BlockReason.UNKNOWN_DESTINATION, f"destination {terms.destination!r} is not allowed", Tier.T3)
    if terms.amount > policy.max_amount_per_action:
        return _block(BlockReason.AMOUNT_OVER_LIMIT, f"amount {terms.amount} exceeds {policy.max_amount_per_action}")
    return GateDecision(True, Tier.T2)


def check_execution(
    authorization: Authorization | None,
    *,
    user_id: str,
    requested: ActionTerms | None,
    now: datetime,
    policy: PermissionPolicy,
    signature_valid: bool,
) -> GateDecision:
    """Order matters: existence, ownership, expiry, replay, tamper, mismatch, policy."""
    if authorization is None:
        return _block(BlockReason.AUTHORIZATION_NOT_FOUND, "no such authorization")
    if authorization.user_id != user_id:
        return _block(BlockReason.WRONG_OWNER, "authorization belongs to another user")
    if authorization.is_expired(now):
        return _block(BlockReason.AUTHORIZATION_EXPIRED, f"expired at {authorization.expires_at.isoformat()}")
    if authorization.consumed_at is not None:
        return _block(BlockReason.AUTHORIZATION_REPLAYED, "authorization already used")
    if not signature_valid:
        return _block(BlockReason.AUTHORIZATION_TAMPERED, "stored terms do not match the signed hash")
    if requested is not None and requested.canonical() != authorization.terms.canonical():
        return _block(
            BlockReason.AUTHORIZATION_MISMATCH,
            f"AUTHORIZED: {authorization.terms.amount} REQUESTED: {requested.amount}",
        )
    return check_terms(authorization.terms, policy)
