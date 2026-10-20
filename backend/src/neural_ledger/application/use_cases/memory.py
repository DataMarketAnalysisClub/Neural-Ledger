"""User memory: consent, proposals, confirmation and deletion (ADR-048). Saved only: nothing here changes a number.

The use cases parse and build; every decision about stored state (account, ownership, consent, single use, staleness,
expected version) is taken by MemoryWrites inside one transaction, with domain/memory/proposals.py. The owner always
comes from the caller's authentication. A chat proposal's origin is the one the server recorded when it prepared it:
a session_id in a confirmation body is accepted by the contract and never trusted as the origin.

Every write that moves the counters runs inside the user's MemoryFence, which the chat also holds at its memory
linearization points (authorized, publish_if_current). A derived read (view, summary) is validated: the counters are
read before and after it, and since every consent or declaration change moves them, equal counters mean it saw one
consistent consent, declarations and evidence; after READ_ATTEMPTS changes in a row it falls back to deriving nothing.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import timedelta

from ...domain.audit.events import Actor, AuditDraft, AuditKind
from ...domain.memory.catalog import (
    CATALOG_VERSION,
    ChatOrigin,
    Declaration,
    MemoryType,
    Origin,
    ProfileOrigin,
    SalaryNet,
    Source,
    applicable,
    declaration_record,
    parse_salary_net,
    upcoming,
)
from ...domain.memory.consent import MemoryState, parse_consent_update
from ...domain.memory.proposals import MemoryProposal, ReadAs, WriteOutcome
from ...domain.memory.salary_check import CHECKER_VERSION, SalaryCheck, check_salary, eligible_inputs
from ...domain.shared.errors import InvalidInput
from ...domain.shared.month import Month
from ..ports import Clock, IdGenerator, MemoryStore, MemoryWrites, StatementStore, TransactionStore
from ..services.memory_fence import MemoryFence

INVALID_INPUT = "INVALID_INPUT"
PERSONA_READ_ONLY = "PERSONA_READ_ONLY"  # checked after the body's structure, before any stored state (memory_error)
_DECLARATION_FIELDS = frozenset({"salary_net", "base", "expected_version", "session_id"})
MAX_SESSION_ID = 120  # contracts/memory/income_declaration.schema.json
READ_ATTEMPTS = 3  # a derived read that keeps seeing the counters move derives nothing
MemoryStamp = tuple[int, int]  # (consent_generation, memory_revision), as application/conversation.py stamps entries


@dataclass(frozen=True, slots=True)
class MemoryOutcome:
    """A memory command's result: DONE, INVALID_INPUT (with field) or a WriteOutcome refusal. Never echoes an amount."""

    status: str
    state: MemoryState | None = None
    field: str | None = None
    changed: bool = False
    chain_id: str | None = None
    deleted_versions: int = 0
    invalidated_proposals: int = 0
    proposal: MemoryProposal | None = None

    @property
    def ok(self) -> bool:
        return self.status == WriteOutcome.DONE.value


# Saved only in this release: no declaration changes a forecast, a capacity or a plan (ADR-049's integration is deferred).
NUMERIC_EFFECT = "saved_only"


def _chains(declarations: tuple[Declaration, ...]) -> list[tuple[str, tuple[Declaration, ...]]]:
    grouped: dict[str, list[Declaration]] = {}
    for d in declarations:
        grouped.setdefault(d.chain_id, []).append(d)
    return [(chain_id, tuple(sorted(versions, key=lambda d: d.version))) for chain_id, versions in grouped.items()]


def salary_check_record(check: SalaryCheck) -> dict:
    """contracts/memory/salary_check.schema.json: derived now, never stored. Saved only, so no reason applies: no
    SALARY_UNIDENTIFIED or SALARY_CONFLICT is invented for an income that is not used."""
    evidence = []
    for e in check.evidence:
        item = {"pay_month": str(e.pay_month), "expected_payday": e.expected_payday.isoformat(), "version": e.version, "outcome": e.outcome.value}
        if e.credit is not None:
            item["credit"] = {
                "statement_id": e.credit.statement_id, "txn_id": e.credit.txn_id, "amount": e.credit.amount,
                "posted_on": e.credit.posted_on.isoformat(),
            }
        evidence.append(item)
    return {
        "status": check.status.value, "matched": check.matched, "missed": check.missed, "evidence": evidence,
        "numeric_effect": NUMERIC_EFFECT, "reasons": [], "params_version": CHECKER_VERSION,
    }


def _invalid(field: str) -> MemoryOutcome:
    return MemoryOutcome(INVALID_INPUT, field=field)


@dataclass(frozen=True, slots=True)
class IncomeDeclaration:
    salary_net: SalaryNet
    base: SalaryNet | None
    expected_version: int


def parse_income_declaration(raw: object) -> IncomeDeclaration:
    """contracts/memory/income_declaration.schema.json, strictly: unknown fields, booleans and other types refused."""
    if not isinstance(raw, Mapping):
        raise InvalidInput("body", "must be an object")
    unknown = sorted(set(raw) - _DECLARATION_FIELDS)
    if unknown:
        raise InvalidInput(unknown[0], "unknown field")
    for name in ("salary_net", "expected_version"):
        if name not in raw:
            raise InvalidInput(name, "is required")
    expected = raw["expected_version"]
    if isinstance(expected, bool) or not isinstance(expected, int) or expected < 0:
        raise InvalidInput("expected_version", "must be an integer from 0")
    session_id = raw.get("session_id")
    if "session_id" in raw and (not isinstance(session_id, str) or len(session_id) > MAX_SESSION_ID):
        raise InvalidInput("session_id", f"must be a string of at most {MAX_SESSION_ID} characters")
    salary = parse_salary_net(raw["salary_net"])
    base = None
    if "base" in raw:
        try:
            base = parse_salary_net(raw["base"])
        except InvalidInput as error:
            raise InvalidInput(error.field.replace("salary_net", "base", 1), error.message) from error
        if expected != 0:
            raise InvalidInput("base", "only a chain's first declaration takes a base")
        if not base.effective_from < salary.effective_from:
            raise InvalidInput("base.effective_from", "the base must start before the change")
    return IncomeDeclaration(salary, base, expected)


class MemoryUseCases:
    def __init__(
        self, store: MemoryStore, writes: MemoryWrites, clock: Clock, ids: IdGenerator, proposal_ttl_seconds: int, *,
        statements: StatementStore | None = None, transactions: TransactionStore | None = None, personas: frozenset[str] = frozenset(),
        fence: MemoryFence | None = None,
    ) -> None:
        self._fence = fence or MemoryFence()
        self._store = store
        self._writes = writes
        self._clock = clock
        self._ids = ids
        self._ttl = timedelta(seconds=proposal_ttl_seconds)  # PP_0_1.proposal_ttl_seconds, injected: no second TTL
        self._statements = statements
        self._transactions = transactions
        self._personas = personas  # shared demo personas take no memory (ADR-048 §9): no items, every write refused

    def is_persona(self, user_id: str) -> bool:
        return user_id in self._personas

    # ---- reads: the user's own data (no consent needed) and what processing may use (consent needed) -------------

    def view(self, user_id: str) -> dict:
        """GET /v1/memory (contracts/memory/memory_view.schema.json). Without consent the declarations are listed, so
        the user can see and delete them, but nothing is derived from them: check is null."""
        view, _ = self._validated(
            user_id, lambda state: self._view(user_id, state, derive=state.granted), lambda state: self._view(user_id, state, derive=False)
        )
        return view

    def _view(self, user_id: str, state: MemoryState, *, derive: bool) -> dict:
        if self.is_persona(user_id):
            return {"catalog_version": CATALOG_VERSION, "consent": state.consent.value, "items": []}
        items = []
        for chain_id, versions in _chains(self._store.for_user(user_id)):
            current, upcoming = self._current_and_upcoming(versions)
            check = self._check(user_id, versions) if derive else None
            items.append({
                "chain_id": chain_id, "type": versions[0].type.value, "versions": len(versions),
                "current": declaration_record(current) if current else None,
                "upcoming": declaration_record(upcoming) if upcoming else None,
                "check": salary_check_record(check) if check else None,
            })
        return {"catalog_version": CATALOG_VERSION, "consent": state.consent.value, "items": items}

    def export(self, user_id: str) -> dict:
        """The memory part of the export (G02): every version of every chain; nothing derived. Needs no consent."""
        declarations = () if self.is_persona(user_id) else self._store.for_user(user_id)
        return {"catalog_version": CATALOG_VERSION, "declarations": [declaration_record(d) for d in declarations]}

    def summary(self, user_id: str) -> tuple[dict, MemoryState]:
        """What get_user_memory gives the model (contracts/memory/memory_summary.schema.json): typed values and the
        derived status only, never text, origin, audit references or store payloads; empty without consent. The state
        returned is the one the summary was derived under."""
        def empty(state: MemoryState) -> dict:
            return {"catalog_version": CATALOG_VERSION, "consent": state.consent.value, "items": []}

        def derive(state: MemoryState) -> dict:
            return self._summary(user_id, state) if state.granted and not self.is_persona(user_id) else empty(state)

        return self._validated(user_id, derive, empty)

    def _summary(self, user_id: str, state: MemoryState) -> dict:
        items = []
        for _, versions in _chains(self._store.for_user(user_id)):
            current, upcoming = self._current_and_upcoming(versions)
            shown = current or upcoming
            assert shown is not None  # a chain has at least one version
            check = self._check(user_id, versions)
            items.append({
                "type": shown.type.value, "amount": shown.value.amount, "effective_from": str(shown.effective_from),
                "status": check.status.value, "numeric_effect": NUMERIC_EFFECT, "reasons": [],
                "upcoming": (
                    {"amount": upcoming.value.amount, "effective_from": str(upcoming.effective_from)}
                    if current is not None and upcoming is not None else None
                ),
            })
        return {"catalog_version": CATALOG_VERSION, "consent": state.consent.value, "items": items}

    def _validated(
        self, user_id: str, derive: Callable[[MemoryState], dict], fallback: Callable[[MemoryState], dict]
    ) -> tuple[dict, MemoryState]:
        """derive under one consistent state, and that state: retried while the counters move during it, else the
        fallback (which derives nothing) under the latest state."""
        for _ in range(READ_ATTEMPTS):
            before = self._writes.state(user_id)
            result = derive(before)
            if self._writes.state(user_id) == before:
                return result, before
        latest = self._writes.state(user_id)
        return fallback(latest), latest

    def _current_and_upcoming(self, versions: tuple[Declaration, ...]) -> tuple[Declaration | None, Declaration | None]:
        month = Month.of(self._clock.now().date())
        return applicable(versions, month), upcoming(versions, month)

    def _check(self, user_id: str, versions: tuple[Declaration, ...]) -> SalaryCheck:
        statements = self._statements.for_user(user_id) if self._statements is not None else ()
        transactions = self._transactions.for_user(user_id) if self._transactions is not None else ()
        return check_salary(versions, *eligible_inputs(user_id, statements, transactions), self._clock.now().date())

    def _event(self, user_id: str, session_id: str, kind: AuditKind) -> AuditDraft:
        return AuditDraft(
            event_id=self._ids.new("evt"), timestamp=self._clock.now(), session_id=session_id, user_id=user_id,
            actor=Actor.USER, kind=kind, detail="pending",  # every adapter replaces the detail inside the transaction
        )

    # ---- consent ------------------------------------------------------------------------------------------------

    def consent(self, user_id: str) -> MemoryState:
        return self._writes.state(user_id)

    def stamp(self, user_id: str) -> MemoryStamp:
        state = self._writes.state(user_id)
        return (state.consent_generation, state.memory_revision)

    def authorized(self, user_id: str, stamp: MemoryStamp) -> bool:
        """The dispatch linearization point: true if the counters are still `stamp`, checked inside the fence, so it is
        ordered against every memory change. It holds at that point only: the caller sends its request after the fence
        is released, and a change after this check is a change during the call (its answer is never published)."""
        with self._fence.held(user_id):
            return self.stamp(user_id) == stamp

    def publish_if_current(self, user_id: str, stamp: MemoryStamp, publish: Callable[[], None]) -> bool:
        """The publication linearization point: run `publish` (a local write, never a network call) only if the
        counters are still `stamp`, with no memory change able to land between the check and the write."""
        with self._fence.held(user_id):
            if self.stamp(user_id) != stamp:
                return False
            publish()
            return True

    def declarations_in_use(self, user_id: str) -> tuple[Declaration, ...]:
        """What processing may read: the user's declarations with the consent granted, none otherwise. Reading one's
        own declarations to see, export or delete them is not processing and does not go through here."""
        if not self._writes.state(user_id).granted:
            return ()
        return self._store.for_user(user_id)

    def set_consent(self, user_id: str, session_id: str, raw: object) -> MemoryOutcome:
        if not isinstance(raw, Mapping) or set(raw) != {"consent"}:
            return _invalid("consent" if isinstance(raw, Mapping) and "consent" in raw else "body")
        try:
            requested = parse_consent_update(raw["consent"])
        except InvalidInput as error:
            return _invalid(error.field)
        if self.is_persona(user_id):
            return MemoryOutcome(PERSONA_READ_ONLY)
        with self._fence.held(user_id):
            result = self._writes.set_consent(user_id, requested, self._event(user_id, session_id, AuditKind.MEMORY_CONSENT_CHANGED))
        return MemoryOutcome(result.outcome.value, result.state, changed=result.changed, invalidated_proposals=result.invalidated_proposals)

    # ---- proposals ----------------------------------------------------------------------------------------------

    def prepare(
        self, user_id: str, origin: ChatOrigin, candidates: tuple[int, ...], effective_from: Month, read_as: ReadAs
    ) -> MemoryOutcome:
        """Store a pending proposal for the card, never a declaration. The candidates and month are the ones the server
        read from the message that started the turn; the origin is that message's reference."""
        if self.is_persona(user_id):
            return MemoryOutcome(PERSONA_READ_ONLY)
        state = self._writes.state(user_id)
        if not state.granted:
            return MemoryOutcome(WriteOutcome.CONSENT_REQUIRED.value, state)
        current = self._store.chain_of_type(user_id, MemoryType.SALARY_NET)
        now = self._clock.now()
        proposal = MemoryProposal(
            proposal_id=self._ids.new("prp"), user_id=user_id, origin=origin, candidates=candidates, effective_from=effective_from,
            read_as=read_as, chain_id=current[-1].chain_id if current else None, expected_version=current[-1].version if current else 0,
            consent_generation=state.consent_generation, memory_revision=state.memory_revision,
            created_at=now, expires_at=now + self._ttl,
        )
        result = self._writes.prepare(proposal)
        return MemoryOutcome(result.outcome.value, result.state, proposal=proposal if result.outcome is WriteOutcome.DONE else None)

    # ---- confirmation -------------------------------------------------------------------------------------------

    def confirm_proposal(self, user_id: str, session_id: str, proposal_id: str, raw: object) -> MemoryOutcome:
        """The card's confirmation: the amount and month the user selected or typed, with the proposal's origin."""
        try:
            body = parse_income_declaration(raw)
        except InvalidInput as error:
            return _invalid(error.field)
        if self.is_persona(user_id):
            return MemoryOutcome(PERSONA_READ_ONLY)
        proposal = self._writes.proposal(user_id, proposal_id)
        if proposal is None:
            return MemoryOutcome(WriteOutcome.NOT_FOUND.value)
        return self._commit(user_id, session_id, proposal_id, proposal.chain_id, body, Source.CHAT, proposal.origin)

    def declare_from_profile(self, user_id: str, session_id: str, raw: object) -> MemoryOutcome:
        """Perfil's declaration (PUT /v1/profile/income): a new version of the user's chain, or its first one."""
        try:
            body = parse_income_declaration(raw)
        except InvalidInput as error:
            return _invalid(error.field)
        if self.is_persona(user_id):
            return MemoryOutcome(PERSONA_READ_ONLY)
        current = self._store.chain_of_type(user_id, MemoryType.SALARY_NET)
        return self._commit(user_id, session_id, None, current[-1].chain_id if current else None, body, Source.PROFILE, ProfileOrigin())

    def _commit(
        self, user_id: str, session_id: str, proposal_id: str | None, chain_id: str | None, body: IncomeDeclaration,
        source: Source, origin: Origin,
    ) -> MemoryOutcome:
        event = self._event(user_id, session_id, AuditKind.MEMORY_CONFIRMED)
        now = event.timestamp
        chain = chain_id or self._ids.new("chn")
        values = (body.base, body.salary_net) if body.base is not None else (body.salary_net,)
        declarations = tuple(
            Declaration(
                memory_id=self._ids.new("mem"), chain_id=chain, version=body.expected_version + 1 + offset, user_id=user_id,
                value=value, confirmed_at=now, source=source, origin=origin, audit_ref=event.event_id,
            )
            for offset, value in enumerate(values)
        )
        with self._fence.held(user_id):
            result = self._writes.confirm(user_id, proposal_id, declarations, body.expected_version, now, event)
        return MemoryOutcome(result.outcome.value, result.state, chain_id=chain if result.outcome is WriteOutcome.DONE else None)

    # ---- deletion -----------------------------------------------------------------------------------------------

    def delete_chain(self, user_id: str, session_id: str, chain_id: str) -> MemoryOutcome:
        """Every version of the user's chain; needs no consent (deletion stays available after revoking)."""
        if self.is_persona(user_id):
            return MemoryOutcome(PERSONA_READ_ONLY)
        if not isinstance(chain_id, str) or not chain_id:
            return MemoryOutcome(WriteOutcome.NOT_FOUND.value)
        with self._fence.held(user_id):
            result = self._writes.delete_chain(user_id, chain_id, self._event(user_id, session_id, AuditKind.MEMORY_DELETED))
        return MemoryOutcome(
            result.outcome.value, result.state, chain_id=chain_id if result.outcome is WriteOutcome.DONE else None,
            deleted_versions=result.deleted_versions, invalidated_proposals=result.invalidated_proposals,
        )
