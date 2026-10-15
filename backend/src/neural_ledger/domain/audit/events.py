"""Audit events (Spec v0 section 10), hash-chained so tampering is detectable.

We log inputs, decisions, probabilities, tool calls, rule outcomes and results.
We never log hidden model reasoning. The export doubles as the sandbox-log evidence.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from datetime import datetime
from enum import Enum
from typing import Any

from ..shared.hashing import canonical_json, sha256_hex
from ..shared.serialization import to_primitive

GENESIS_HASH = "0" * 64


class AuditKind(str, Enum):
    DECISION = "DECISION"
    TOOL_CALL = "TOOL_CALL"
    CLARIFICATION_REQUESTED = "CLARIFICATION_REQUESTED"
    INJECTION_FLAGGED = "INJECTION_FLAGGED"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    PROPOSAL_CREATED = "PROPOSAL_CREATED"
    ACTION_CONFIRMED = "ACTION_CONFIRMED"
    EXECUTION_STARTED = "EXECUTION_STARTED"
    ACTION_EXECUTED = "ACTION_EXECUTED"
    ACTION_FAILED = "ACTION_FAILED"
    ACTION_BLOCKED = "ACTION_BLOCKED"
    STATEMENT_IMPORTED = "STATEMENT_IMPORTED"
    PROFILE_UPDATED = "PROFILE_UPDATED"


class Actor(str, Enum):
    USER = "user"
    AGENT = "agent"
    SYSTEM = "system"


@dataclass(frozen=True, slots=True)
class DecisionCheck:
    model: str
    key: str
    label: str
    confidence: float


@dataclass(frozen=True, slots=True)
class AuditDraft:
    event_id: str
    timestamp: datetime
    session_id: str
    actor: Actor
    kind: AuditKind
    user_intent: str | None = None
    intent_confidence: float | None = None
    tool_requested: str | None = None
    tool_parameters_hash: str | None = None
    forecast_snapshot_id: str | None = None
    policy_version: str | None = None
    decision_model_checks: tuple[DecisionCheck, ...] = ()
    permission_tier: str | None = None
    authorization_id: str | None = None
    execution_result: str | None = None
    blocked_reason: str | None = None
    model_version: str | None = None
    detail: str | None = None
    user_id: str | None = None  # owner of the event; reads are scoped to it (None = system-wide)


@dataclass(frozen=True, slots=True)
class AuditEvent:
    sequence: int
    prev_hash: str
    event_hash: str
    draft: AuditDraft

    def to_record(self) -> dict[str, Any]:
        record = _hashable(self.draft, self.sequence, self.prev_hash)
        record["event_hash"] = self.event_hash
        return record

    @staticmethod
    def from_record(record: Mapping[str, Any]) -> AuditEvent:
        checks = tuple(DecisionCheck(**c) for c in record.get("decision_model_checks", ()))
        names = {f.name for f in fields(AuditDraft)}
        values = {k: v for k, v in record.items() if k in names}
        values.update(
            timestamp=datetime.fromisoformat(record["timestamp"]),
            actor=Actor(record["actor"]),
            kind=AuditKind(record["kind"]),
            decision_model_checks=checks,
        )
        return AuditEvent(record["sequence"], record["prev_hash"], record["event_hash"], AuditDraft(**values))


def _hashable(draft: AuditDraft, sequence: int, prev_hash: str) -> dict[str, Any]:
    record = to_primitive(draft)
    record["sequence"] = sequence
    record["prev_hash"] = prev_hash
    return record


def compute_hash(draft: AuditDraft, sequence: int, prev_hash: str) -> str:
    return sha256_hex(canonical_json(_hashable(draft, sequence, prev_hash)))


def seal(draft: AuditDraft, sequence: int, prev_hash: str) -> AuditEvent:
    return AuditEvent(sequence, prev_hash, compute_hash(draft, sequence, prev_hash), draft)


@dataclass(frozen=True, slots=True)
class ChainCheck:
    ok: bool
    checked: int
    broken_at: int | None = None
    reason: str | None = None


def verify_chain(events: Sequence[AuditEvent]) -> ChainCheck:
    prev = GENESIS_HASH
    for index, event in enumerate(sorted(events, key=lambda e: e.sequence), start=1):
        if event.sequence != index:
            return ChainCheck(False, index - 1, event.sequence, "sequence gap")
        if event.prev_hash != prev:
            return ChainCheck(False, index - 1, event.sequence, "prev_hash does not link")
        if compute_hash(event.draft, event.sequence, event.prev_hash) != event.event_hash:
            return ChainCheck(False, index - 1, event.sequence, "event content changed")
        prev = event.event_hash
    return ChainCheck(True, len(events))
