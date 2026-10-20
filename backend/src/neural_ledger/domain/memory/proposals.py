"""Income proposals and the rules a confirmation must pass (ADR-048 §5-6).

A proposal is prepared from the message that started a chat turn and waits, server side, for the user to confirm it
in the card. It records what the server established, never what a client or a model says: its owner, the chat origin
(session and message ids, never the text nor its hash), the candidates and the pay month read from that message, the
chain and the version it would extend, the consent generation and memory revision of its moment, and when it expires.
Preparing one stores no declaration. It is used once.

`decide_confirmation` is the single order in which a confirmation is refused (contracts/memory/memory_error.schema.json):
the owned proposal, the current consent, single use, staleness (expiry, invalidation, any captured state changed),
then the request's expected_version. Every adapter evaluates it on the state it read inside its write transaction.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum

from ..audit.events import AuditDraft
from ..shared.errors import InvalidInput
from ..shared.month import Month
from .catalog import MAX_SALARY_NET, ChatOrigin, Declaration, MemoryType, check_appended
from .consent import MemoryState


class ProposalStatus(str, Enum):
    READY = "READY"  # one amount read, prefilled
    CHOOSE_AMOUNT = "CHOOSE_AMOUNT"  # several, the user picks; nothing decides which is the old or the new salary
    ASK_AMOUNT = "ASK_AMOUNT"  # none, the card asks; no amount is invented


class ReadAs(str, Enum):
    EXPLICIT_YEAR = "explicit_year"
    NEXT_OCCURRENCE = "next_occurrence"
    NEXT_PAYDAY = "next_payday"


class ProposalState(str, Enum):
    PENDING = "pending"
    CONSUMED = "consumed"
    INVALIDATED = "invalidated"  # its chain was deleted or the consent revoked: it can never be confirmed


class WriteOutcome(str, Enum):
    """What a memory write did; every refusal leaves no writes. The HTTP layer maps these to memory_error codes."""

    DONE = "DONE"
    NOT_WRITABLE = "NOT_WRITABLE"  # the account no longer exists (deleted meanwhile) or is a shared persona
    NOT_FOUND = "NOT_FOUND"  # unknown, or another user's: the same answer
    CONSENT_REQUIRED = "CONSENT_REQUIRED"
    PROPOSAL_USED = "PROPOSAL_USED"
    PROPOSAL_STALE = "PROPOSAL_STALE"
    VERSION_CONFLICT = "VERSION_CONFLICT"


def _id(field: str, value: object) -> None:
    if not isinstance(value, str) or not value:
        raise InvalidInput(field, "must be a non-empty string")


def _aware(field: str, value: object) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise InvalidInput(field, "must be a date-time with a time zone")


@dataclass(frozen=True, slots=True)
class MemoryProposal:
    proposal_id: str
    user_id: str
    origin: ChatOrigin
    candidates: tuple[int, ...]  # read from the current message, in the order written, without repeats
    effective_from: Month
    read_as: ReadAs
    chain_id: str | None  # the chain it extends; None for the first declaration
    expected_version: int  # the chain's last version when prepared, 0 for none
    consent_generation: int
    memory_revision: int
    created_at: datetime
    expires_at: datetime
    state: ProposalState = ProposalState.PENDING
    type: MemoryType = MemoryType.SALARY_NET

    def __post_init__(self) -> None:
        _id("proposal_id", self.proposal_id)
        _id("user_id", self.user_id)
        if not isinstance(self.origin, ChatOrigin):
            raise InvalidInput("origin", "a proposal comes from a chat message")
        ChatOrigin(self.origin.session_id, self.origin.message_id)
        if not isinstance(self.candidates, tuple) or any(
            isinstance(c, bool) or not isinstance(c, int) or not 1 <= c <= MAX_SALARY_NET for c in self.candidates
        ) or len(set(self.candidates)) != len(self.candidates):
            raise InvalidInput("candidates", f"distinct integer CLP amounts from 1 to {MAX_SALARY_NET}")
        if not isinstance(self.effective_from, Month):
            raise InvalidInput("effective_from", "must be a pay month")
        if not isinstance(self.read_as, ReadAs) or not isinstance(self.state, ProposalState) or not isinstance(self.type, MemoryType):
            raise InvalidInput("proposal", "read_as, state and type must come from their catalogs")
        if self.chain_id is not None:
            _id("chain_id", self.chain_id)
        for name in ("expected_version", "consent_generation", "memory_revision"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise InvalidInput(name, "must be a non-negative integer")
        if (self.chain_id is None) != (self.expected_version == 0):
            raise InvalidInput("expected_version", "0 exactly when there is no chain yet")
        _aware("created_at", self.created_at)
        _aware("expires_at", self.expires_at)
        if self.expires_at <= self.created_at:
            raise InvalidInput("expires_at", "must be after created_at")

    @property
    def status(self) -> ProposalStatus:
        if not self.candidates:
            return ProposalStatus.ASK_AMOUNT
        return ProposalStatus.READY if len(self.candidates) == 1 else ProposalStatus.CHOOSE_AMOUNT

    @property
    def needs_base(self) -> bool:
        """The chain has no version yet: the card may ask for the previous salary and its pay month."""
        return self.chain_id is None

    def expired(self, now: datetime) -> bool:
        return now >= self.expires_at


def decide_preparation(*, writable: bool, state: MemoryState, proposal: MemoryProposal) -> WriteOutcome:
    """Whether a proposal may be stored now: the account is there, the consent granted, nothing changed since it was read."""
    if not writable:
        return WriteOutcome.NOT_WRITABLE
    if not state.granted:
        return WriteOutcome.CONSENT_REQUIRED
    if (proposal.consent_generation, proposal.memory_revision) != (state.consent_generation, state.memory_revision):
        return WriteOutcome.PROPOSAL_STALE
    return WriteOutcome.DONE


def decide_confirmation(
    *,
    user_id: str,
    writable: bool,
    state: MemoryState,
    proposal_id: str | None,
    proposal: MemoryProposal | None,
    chain_id: str | None,
    head_version: int,
    batch_chain_id: str,
    expected_version: int,
    now: datetime,
) -> WriteOutcome:
    """The outcome of confirming a declaration (proposal_id set: from the card; None: from Perfil).

    `chain_id` and `head_version` are the user's chain of the type as stored now (None and 0 for none); `batch_chain_id`
    is the chain the declarations to append name. The order is the contract's error precedence.
    """
    if not writable:
        return WriteOutcome.NOT_WRITABLE
    if proposal_id is not None and (proposal is None or proposal.user_id != user_id or proposal.proposal_id != proposal_id):
        return WriteOutcome.NOT_FOUND
    if not state.granted:
        return WriteOutcome.CONSENT_REQUIRED
    if proposal is not None:
        if proposal.state is ProposalState.CONSUMED:
            return WriteOutcome.PROPOSAL_USED
        if (
            proposal.state is ProposalState.INVALIDATED or proposal.expired(now)
            or proposal.consent_generation != state.consent_generation or proposal.memory_revision != state.memory_revision
            or proposal.chain_id != chain_id or proposal.expected_version != head_version
        ):
            return WriteOutcome.PROPOSAL_STALE
    if expected_version != head_version or (chain_id is not None and batch_chain_id != chain_id):
        return WriteOutcome.VERSION_CONFLICT
    return WriteOutcome.DONE


def proposal_record(p: MemoryProposal) -> dict:
    """The sealed payload of a stored proposal: references, typed values and counters, never message text."""
    return {
        "proposal_id": p.proposal_id,
        "origin": {"kind": "chat", "session_id": p.origin.session_id, "message_id": p.origin.message_id},
        "type": p.type.value,
        "candidates": list(p.candidates),
        "effective_from": str(p.effective_from),
        "read_as": p.read_as.value,
        "chain_id": p.chain_id,
        "expected_version": p.expected_version,
        "consent_generation": p.consent_generation,
        "memory_revision": p.memory_revision,
        "created_at": p.created_at.isoformat(),
        "expires_at": p.expires_at.isoformat(),
        "state": p.state.value,
    }


_PROPOSAL_FIELDS = frozenset({
    "proposal_id", "origin", "type", "candidates", "effective_from", "read_as", "chain_id", "expected_version",
    "consent_generation", "memory_revision", "created_at", "expires_at", "state",
})


def parse_proposal(raw: object, user_id: str) -> MemoryProposal:
    if not isinstance(raw, Mapping) or set(raw) != _PROPOSAL_FIELDS:
        raise InvalidInput("proposal", "must hold exactly the fields of a stored proposal")
    origin = raw["origin"]
    if not isinstance(origin, Mapping) or set(origin) != {"kind", "session_id", "message_id"} or origin["kind"] != "chat":
        raise InvalidInput("origin", "a proposal comes from a chat message")
    try:
        return MemoryProposal(
            proposal_id=raw["proposal_id"], user_id=user_id, origin=ChatOrigin(origin["session_id"], origin["message_id"]),
            candidates=tuple(raw["candidates"]), effective_from=Month.parse(raw["effective_from"]), read_as=ReadAs(raw["read_as"]),
            chain_id=raw["chain_id"], expected_version=raw["expected_version"], consent_generation=raw["consent_generation"],
            memory_revision=raw["memory_revision"], created_at=datetime.fromisoformat(raw["created_at"]),
            expires_at=datetime.fromisoformat(raw["expires_at"]), state=ProposalState(raw["state"]), type=MemoryType(raw["type"]),
        )
    except (TypeError, ValueError) as error:
        raise InvalidInput("proposal", "a stored proposal is malformed") from error


# ---- audit details: codes, references and counts, never an amount or a message -----------------------------

def consent_detail(before: MemoryState, after: MemoryState) -> str:
    return f"consent={before.consent.value}->{after.consent.value} generation={after.consent_generation}"


def confirmation_detail(
    *, chain_id: str, source: str, proposal_id: str | None, from_version: int, versions: int, revision: int
) -> str:
    return (
        f"type={MemoryType.SALARY_NET.value} chain={chain_id} source={source} proposal={proposal_id or 'none'} "
        f"from_version={from_version} versions={versions} revision={revision}"
    )


def deletion_detail(*, chain_id: str, deleted_versions: int, invalidated_proposals: int, revision: int) -> str:
    return f"chain={chain_id} deleted_versions={deleted_versions} invalidated_proposals={invalidated_proposals} revision={revision}"


def check_confirmation(user_id: str, declarations: Sequence[Declaration], expected_version: int, event: AuditDraft) -> None:
    """What MemoryWrites.confirm refuses with ValueError in every adapter, before it looks at any stored state."""
    check_appended(declarations, expected_version)
    if declarations[0].user_id != user_id or event.user_id != user_id:
        raise ValueError("memory ownership mismatch")
    if any(d.audit_ref != event.event_id for d in declarations):
        raise ValueError("every confirmed version refers to the confirmation's audit event")


def confirmation_event(
    event: AuditDraft, proposal_id: str | None, declarations: Sequence[Declaration], expected_version: int, after: MemoryState
) -> AuditDraft:
    detail = confirmation_detail(
        chain_id=declarations[0].chain_id, source=declarations[-1].source.value, proposal_id=proposal_id,
        from_version=expected_version, versions=len(declarations), revision=after.memory_revision,
    )
    return replace(event, detail=detail)
