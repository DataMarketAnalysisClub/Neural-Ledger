"""Audit events (Spec v0 section 10), hash-chained so tampering is detectable.

We log inputs, decisions, probabilities, tool calls, rule outcomes and results.
We never log hidden model reasoning. The export doubles as the sandbox-log evidence.

Erasure (account deletion, a demo persona's reset). The chain is one log for every user, so removing a user's
events would break it for everyone. Instead each of them becomes a tombstone: same sequence, prev_hash and
event_hash, so the links still verify, but every field that said anything about the user is gone (kind ERASED,
actor system, no user, no session, a timestamp of the erasure). Its content can no longer be re-hashed, so a
tombstone is accepted only when a later ACCOUNT_DELETED or DEMO_DATA_RESET event commits to it: that event's
detail names how many sequences it erased and a sha256 of the list. Turning any other event into a tombstone,
or erasing one more, changes what that committed event would have to say, so verification fails.
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
    DOCUMENT_ROUTED = "DOCUMENT_ROUTED"  # a file dropped on the copilot was routed: statement, receipt or unknown (ADR-039)
    RECEIPT_IMPORTED = "RECEIPT_IMPORTED"
    EXPENSE_LOGGED = "EXPENSE_LOGGED"  # the user confirmed an expense they told the copilot about (ADR-039)
    RECEIPT_CORRECTED = "RECEIPT_CORRECTED"  # the user typed a receipt's total or date the reader could not read (ADR-039)
    CATEGORY_CHANGED = "CATEGORY_CHANGED"  # the user set a transaction's category (ADR-023)
    PROFILE_UPDATED = "PROFILE_UPDATED"
    USER_REGISTERED = "USER_REGISTERED"
    SESSION_STARTED = "SESSION_STARTED"
    SESSION_ENDED = "SESSION_ENDED"
    ACCOUNT_DELETED = "ACCOUNT_DELETED"  # the user deleted their account; detail commits to the events it erased
    DEMO_DATA_RESET = "DEMO_DATA_RESET"  # a shared demo persona's stored data was reset; same commitment
    ERASED = "ERASED"  # a tombstone: an erased event's place in the chain, content gone
    # An investment account at another institution (ADR-044): linked, read again, or unlinked by the user, or one of
    # its statements imported or deleted. The detail names the provider and counts only: never the email, the token,
    # a goal name or an amount.
    INVESTMENTS_LINKED = "INVESTMENTS_LINKED"
    INVESTMENTS_SYNCED = "INVESTMENTS_SYNCED"
    INVESTMENTS_UNLINKED = "INVESTMENTS_UNLINKED"
    INVESTMENT_DOCUMENT_IMPORTED = "INVESTMENT_DOCUMENT_IMPORTED"
    INVESTMENT_DOCUMENTS_REMOVED = "INVESTMENT_DOCUMENTS_REMOVED"


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


ERASURE_KINDS = frozenset({AuditKind.ACCOUNT_DELETED, AuditKind.DEMO_DATA_RESET})
ERASED_SESSION = "erased"
_ERASED_BY = "erased_by="


def erasure_commitment(sequences: Sequence[int]) -> str:
    return sha256_hex(",".join(str(n) for n in sorted(sequences)))


def erasure_detail(sequences: Sequence[int], counts: Mapping[str, int]) -> str:
    """What an erasure event records: how many rows went per table and exactly which audit sequences it erased.

    Counts and sequence numbers only: never the user id, an email or a session."""
    rows = ";".join(f"{table}={counts[table]}" for table in sorted(counts))
    return f"erased_events={len(sequences)};erased_sha256={erasure_commitment(sequences)}" + (f";{rows}" if rows else "")


def tombstone(event: AuditEvent, erasure_event_id: str, at: datetime) -> AuditEvent:
    """The event's place in the chain without its content (see the module docstring)."""
    draft = AuditDraft(
        event_id=event.draft.event_id, timestamp=at, session_id=ERASED_SESSION, actor=Actor.SYSTEM,
        kind=AuditKind.ERASED, detail=f"{_ERASED_BY}{erasure_event_id}",
    )
    return AuditEvent(event.sequence, event.prev_hash, event.event_hash, draft)


def _committed(detail: str | None) -> tuple[int, str] | None:
    parts = dict(part.split("=", 1) for part in (detail or "").split(";") if "=" in part)
    try:
        return int(parts["erased_events"]), parts["erased_sha256"]
    except (KeyError, ValueError):
        return None


def verify_chain(events: Sequence[AuditEvent]) -> ChainCheck:
    prev = GENESIS_HASH
    erased: dict[str, list[int]] = {}  # erasure event id -> the tombstones that name it
    erasures: dict[str, AuditEvent] = {}
    for index, event in enumerate(sorted(events, key=lambda e: e.sequence), start=1):
        if event.sequence != index:
            return ChainCheck(False, index - 1, event.sequence, "sequence gap")
        if event.prev_hash != prev:
            return ChainCheck(False, index - 1, event.sequence, "prev_hash does not link")
        if event.draft.kind is AuditKind.ERASED:
            by = (event.draft.detail or "").removeprefix(_ERASED_BY)
            if by in erasures:  # an erasure erases events before it, never after
                return ChainCheck(False, index - 1, event.sequence, "erased after its erasure event")
            erased.setdefault(by, []).append(event.sequence)
        elif compute_hash(event.draft, event.sequence, event.prev_hash) != event.event_hash:
            return ChainCheck(False, index - 1, event.sequence, "event content changed")
        if event.draft.kind in ERASURE_KINDS:
            erasures[event.draft.event_id] = event
        prev = event.event_hash
    for by, sequences in erased.items():
        commitment = _committed(erasures[by].draft.detail) if by in erasures else None
        if commitment != (len(sequences), erasure_commitment(sequences)):
            return ChainCheck(False, min(sequences) - 1, min(sequences), "erasure not recorded by a later erasure event")
    for event_id, event in erasures.items():
        commitment = _committed(event.draft.detail)
        if commitment is None or commitment[0] != len(erased.get(event_id, ())):
            return ChainCheck(False, event.sequence - 1, event.sequence, "erasure event does not match its tombstones")
    return ChainCheck(True, len(events))
