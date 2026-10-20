"""ADR-048 step 7: consent, proposals, the atomic confirmation and the chain deletion, on both adapters.

Every write is one transaction that rechecks the account, the owner, the consent and what a proposal captured; a
refusal and a failure at any stage leave nothing written. Nothing here changes a financial number: memory is saved
only in this release.
"""

from __future__ import annotations

import threading
from datetime import timedelta

import pytest

from neural_ledger.application.use_cases.memory import MemoryUseCases
from neural_ledger.bootstrap.container import build
from neural_ledger.domain.audit.events import AuditKind, verify_chain
from neural_ledger.domain.memory.catalog import ChatOrigin, MemoryType, ProfileOrigin, Source
from neural_ledger.domain.memory.consent import Consent
from neural_ledger.domain.memory.proposals import ProposalState, ReadAs
from neural_ledger.domain.permissions.policy import PP_0_1
from neural_ledger.domain.shared.month import Month
from tests.conftest import make_settings

KEY = "5c" * 32
PASSWORD = "synthetic-password-mem"
AMOUNT = 1_234_567  # distinctive: no audit detail, error or raw file may contain it
TTL = timedelta(seconds=PP_0_1.proposal_ttl_seconds)


class World:
    def __init__(self, persistence: str, tmp_path) -> None:
        extra = {"persistence": "sqlite", "sqlite_path": str(tmp_path / "mem.db"), "data_key": KEY} if persistence == "sqlite" else {}
        self.persistence = persistence
        self.services, self.adapters = build(make_settings(auth="accounts", app_origins=("http://localhost:3000",), **extra))
        self.memory: MemoryUseCases = self.services.memory
        self.store = self.adapters.memory_store
        self.writes = self.adapters.memory_writes
        self.clock = self.adapters.clock
        self.ana, self.ana_token = self.signup("ana.memory@accounts.invalid", "Ana")
        self.bea, self.bea_token = self.signup("bea.memory@accounts.invalid", "Bea")

    def signup(self, email: str, name: str) -> tuple[str, str]:
        outcome = self.services.accounts.signup(email, PASSWORD, name, sandbox_notice="sandbox-1")
        assert outcome.ok, outcome
        return outcome.session.user_id, outcome.session.token

    def grant(self, user_id: str) -> None:
        assert self.memory.set_consent(user_id, "s_1", {"consent": "granted"}).ok

    def propose(self, user_id: str, candidates=(AMOUNT,), month: str = "2026-11", message_id: str = "msg_1"):
        return self.memory.prepare(user_id, ChatOrigin("s_1", message_id), tuple(candidates), Month.parse(month), ReadAs.NEXT_OCCURRENCE)

    def confirm(self, user_id: str, proposal_id: str, amount: int = AMOUNT, month: str = "2026-11", expected: int = 0, **extra):
        body = {"salary_net": {"amount": amount, "net": True, "effective_from": month}, "expected_version": expected, **extra}
        return self.memory.confirm_proposal(user_id, "s_1", proposal_id, body)

    def declare(self, user_id: str, amount: int = AMOUNT, month: str = "2026-11", expected: int = 0, **extra):
        body = {"salary_net": {"amount": amount, "net": True, "effective_from": month}, "expected_version": expected, **extra}
        return self.memory.declare_from_profile(user_id, "s_1", body)

    def events(self, kind: AuditKind | None = None, user_id: str | None = None):
        return [
            e for e in self.adapters.audit_log.events()
            if (kind is None or e.draft.kind is kind) and (user_id is None or e.draft.user_id == user_id)
        ]

    def snapshot(self, user_id: str):
        """Everything memory holds for a user plus the whole audit log: equal before and after means no writes."""
        return (self.store.for_user(user_id), self.writes.state(user_id), self._proposals(user_id), tuple(self.adapters.audit_log.events()))

    def _proposals(self, user_id: str):
        if self.persistence == "memory":
            return tuple(sorted((p for p in self.store._proposals.values() if p.user_id == user_id), key=lambda p: p.proposal_id))
        rows = self.store._db.fetchall("SELECT proposal_id FROM memory_proposals WHERE user_id = ? ORDER BY proposal_id", (user_id,))
        return tuple(self.writes.proposal(user_id, pid) for (pid,) in rows)


@pytest.fixture(params=["memory", "sqlite"])
def world(request, tmp_path) -> World:
    return World(request.param, tmp_path)


# ---- consent and its counters -----------------------------------------------------------------------------

def test_consent_starts_missing_and_each_actual_change_advances_the_generation_once(world):
    state = world.memory.consent(world.ana)
    assert (state.consent, state.consent_generation, state.memory_revision) == (Consent.MISSING, 0, 0)
    assert world.memory.set_consent(world.ana, "s_1", {"consent": "revoked"}).changed is False  # nothing to revoke
    granted = world.memory.set_consent(world.ana, "s_1", {"consent": "granted"})
    assert granted.ok and granted.changed and granted.state.consent_generation == 1
    again = world.memory.set_consent(world.ana, "s_1", {"consent": "granted"})
    assert again.ok and not again.changed and again.state.consent_generation == 1
    revoked = world.memory.set_consent(world.ana, "s_1", {"consent": "revoked"})
    assert revoked.changed and (revoked.state.consent, revoked.state.consent_generation) == (Consent.REVOKED, 2)
    assert not world.memory.set_consent(world.ana, "s_1", {"consent": "revoked"}).changed
    assert [e.draft.detail for e in world.events(AuditKind.MEMORY_CONSENT_CHANGED)] == [
        "consent=missing->granted generation=1", "consent=granted->revoked generation=2",
    ]
    assert world.memory.consent(world.bea).consent is Consent.MISSING  # per user


@pytest.mark.parametrize(
    "body",
    [{"consent": "missing"}, {"consent": True}, {"consent": "GRANTED"}, {"consent": "granted", "user_id": "bea"}, {}, ["granted"], None],
)
def test_a_malformed_consent_update_changes_nothing(world, body):
    before = world.snapshot(world.ana)
    outcome = world.memory.set_consent(world.ana, "s_1", body)
    assert outcome.status == "INVALID_INPUT" and outcome.field
    assert world.snapshot(world.ana) == before


# ---- who can write ----------------------------------------------------------------------------------------

def test_a_shared_persona_or_an_unknown_user_writes_nothing(world):
    for user, refusal in (("camila", "PERSONA_READ_ONLY"), ("usr_never_registered", "NOT_WRITABLE")):
        before = world.snapshot(user)
        assert world.memory.set_consent(user, "s_1", {"consent": "granted"}).status == refusal
        assert world.declare(user).status in ("PERSONA_READ_ONLY", "CONSENT_REQUIRED", "NOT_WRITABLE")
        assert world.memory.delete_chain(user, "s_1", "chn_any").status == refusal
        assert world.snapshot(user) == before


def test_without_consent_nothing_is_proposed_confirmed_or_edited(world):
    before = world.snapshot(world.ana)
    assert world.propose(world.ana).status == "CONSENT_REQUIRED"
    assert world.declare(world.ana).status == "CONSENT_REQUIRED"
    assert world.snapshot(world.ana) == before


# ---- preparing stores a proposal, never a declaration ------------------------------------------------------

def test_a_prepared_proposal_captures_the_state_and_stores_no_declaration(world):
    world.grant(world.ana)
    outcome = world.propose(world.ana, candidates=(1_100_000, AMOUNT))
    proposal = outcome.proposal
    assert outcome.ok and proposal.status.value == "CHOOSE_AMOUNT" and proposal.needs_base
    assert (proposal.consent_generation, proposal.memory_revision, proposal.chain_id, proposal.expected_version) == (1, 0, None, 0)
    assert proposal.expires_at - proposal.created_at == TTL  # the injected PP_0_1 TTL, not a second one
    assert world.writes.proposal(world.ana, proposal.proposal_id) == proposal
    assert world.writes.proposal(world.bea, proposal.proposal_id) is None  # another user's is not found
    assert world.store.for_user(world.ana) == ()
    assert world.events(AuditKind.MEMORY_CONFIRMED) == []


# ---- the confirmation -------------------------------------------------------------------------------------

def test_a_confirmed_proposal_stores_one_version_with_the_servers_origin(world):
    world.grant(world.ana)
    proposal = world.propose(world.ana, message_id="msg_real").proposal
    outcome = world.confirm(world.ana, proposal.proposal_id, session_id="s_forged_by_the_client")
    assert outcome.ok and outcome.state.memory_revision == 1
    (stored,) = world.store.chain_of_type(world.ana, MemoryType.SALARY_NET)
    assert (stored.version, stored.value.amount, stored.source) == (1, AMOUNT, Source.CHAT)
    assert stored.origin == ChatOrigin("s_1", "msg_real")  # the proposal's, never the body's session_id
    (event,) = world.events(AuditKind.MEMORY_CONFIRMED)
    assert stored.audit_ref == event.draft.event_id and event.draft.user_id == world.ana
    assert str(AMOUNT) not in event.draft.detail and "proposal=" + proposal.proposal_id in event.draft.detail
    assert world.writes.proposal(world.ana, proposal.proposal_id).state is ProposalState.CONSUMED
    assert verify_chain(world.adapters.audit_log.events()).ok


def test_the_user_may_type_another_amount_and_month_than_the_message_said(world):
    world.grant(world.ana)
    proposal = world.propose(world.ana, candidates=()).proposal  # ASK_AMOUNT: nothing invented
    assert proposal.status.value == "ASK_AMOUNT" and proposal.candidates == ()
    assert world.confirm(world.ana, proposal.proposal_id, amount=987_654, month="2026-12").ok
    assert world.store.chain_of_type(world.ana, MemoryType.SALARY_NET)[0].value.amount == 987_654


def test_a_replayed_confirmation_is_used_and_writes_nothing(world):
    world.grant(world.ana)
    proposal = world.propose(world.ana).proposal
    assert world.confirm(world.ana, proposal.proposal_id).ok
    before = world.snapshot(world.ana)
    assert world.confirm(world.ana, proposal.proposal_id).status == "PROPOSAL_USED"
    assert world.confirm(world.ana, proposal.proposal_id, expected=1).status == "PROPOSAL_USED"
    assert world.snapshot(world.ana) == before


def test_another_users_or_an_unknown_proposal_is_not_found(world):
    world.grant(world.ana)
    proposal = world.propose(world.ana).proposal
    before = world.snapshot(world.bea)
    assert world.confirm(world.bea, proposal.proposal_id).status == "NOT_FOUND"  # bea has no consent: 404 still wins
    assert world.snapshot(world.bea) == before
    world.grant(world.bea)
    before_ana, before_bea = world.snapshot(world.ana), world.snapshot(world.bea)
    assert world.confirm(world.bea, proposal.proposal_id).status == "NOT_FOUND"
    assert world.confirm(world.ana, "prp_unknown").status == "NOT_FOUND"
    assert world.snapshot(world.ana) == before_ana and world.snapshot(world.bea) == before_bea


@pytest.mark.parametrize(("offset", "expected"), [(-timedelta(microseconds=1), "DONE"), (timedelta(0), "PROPOSAL_STALE"), (timedelta(seconds=1), "PROPOSAL_STALE")])
def test_a_proposal_expires_exactly_at_its_expiry(world, offset, expected):
    world.grant(world.ana)
    proposal = world.propose(world.ana).proposal
    world.clock.advance(seconds=(TTL + offset).total_seconds())
    before = world.snapshot(world.ana)
    assert world.confirm(world.ana, proposal.proposal_id).status == expected
    if expected != "DONE":
        assert world.snapshot(world.ana) == before
        assert world.writes.proposal(world.ana, proposal.proposal_id).expires_at == proposal.expires_at  # never refreshed


def test_the_error_precedence_is_consent_then_used_then_stale_then_version(world):
    world.grant(world.ana)
    used = world.propose(world.ana).proposal
    assert world.confirm(world.ana, used.proposal_id).ok
    pending = world.propose(world.ana, message_id="msg_2").proposal  # captured revision 1, chain v1
    world.clock.advance(seconds=TTL.total_seconds() + 1)  # both expired now
    assert world.confirm(world.ana, used.proposal_id, expected=1).status == "PROPOSAL_USED"  # used before stale
    assert world.confirm(world.ana, pending.proposal_id, expected=7).status == "PROPOSAL_STALE"  # stale before version
    world.memory.set_consent(world.ana, "s_1", {"consent": "revoked"})
    assert world.confirm(world.ana, used.proposal_id, expected=1).status == "CONSENT_REQUIRED"  # consent before used
    world.grant(world.ana)
    assert world.declare(world.ana, expected=0).status == "VERSION_CONFLICT"  # Perfil: the head is 1
    assert world.declare(world.ana, expected=1).ok


def test_a_base_and_a_change_are_confirmed_together_or_not_at_all(world):
    world.grant(world.ana)
    proposal = world.propose(world.ana).proposal
    base = {"amount": 1_000_000, "net": True, "effective_from": "2026-06"}
    assert world.confirm(world.ana, proposal.proposal_id, base={**base, "effective_from": "2026-11"}).status == "INVALID_INPUT"
    assert world.confirm(world.ana, proposal.proposal_id, base={**base, "amount": True}).status == "INVALID_INPUT"
    assert world.confirm(world.ana, proposal.proposal_id, base=base).ok
    versions = world.store.chain_of_type(world.ana, MemoryType.SALARY_NET)
    assert [(d.version, d.value.amount) for d in versions] == [(1, 1_000_000), (2, AMOUNT)]
    assert len({d.audit_ref for d in versions}) == 1 and len(world.events(AuditKind.MEMORY_CONFIRMED)) == 1
    assert world.declare(world.ana, expected=2, base=base).status == "INVALID_INPUT"  # a base only for a new chain


@pytest.mark.parametrize(
    "body",
    [
        {"salary_net": {"amount": True, "net": True, "effective_from": "2026-11"}, "expected_version": 0},
        {"salary_net": {"amount": "1200000", "net": True, "effective_from": "2026-11"}, "expected_version": 0},
        {"salary_net": {"amount": 1.5, "net": True, "effective_from": "2026-11"}, "expected_version": 0},
        {"salary_net": {"amount": 0, "net": True, "effective_from": "2026-11"}, "expected_version": 0},
        {"salary_net": {"amount": 1, "net": False, "effective_from": "2026-11"}, "expected_version": 0},
        {"salary_net": {"amount": 1, "net": True, "effective_from": "2026-11"}, "expected_version": True},
        {"salary_net": {"amount": 1, "net": True, "effective_from": "2026-11"}, "expected_version": 0, "user_id": "bea"},
        {"salary_net": {"amount": 1, "net": True, "effective_from": "2026-11"}},
        {"expected_version": 0},
        "1200000",
    ],
)
def test_a_malformed_declaration_body_writes_nothing_and_echoes_no_amount(world, body):
    world.grant(world.ana)
    proposal = world.propose(world.ana).proposal
    before = world.snapshot(world.ana)
    for outcome in (world.memory.confirm_proposal(world.ana, "s_1", proposal.proposal_id, body), world.memory.declare_from_profile(world.ana, "s_1", body)):
        assert outcome.status == "INVALID_INPUT" and outcome.field and "1200000" not in repr(outcome)
    assert world.snapshot(world.ana) == before


# ---- revocation and deletion invalidate; nothing revives a proposal -----------------------------------------

def test_revoking_keeps_declarations_and_reconsenting_never_revives_a_proposal(world):
    world.grant(world.ana)
    assert world.declare(world.ana).ok
    proposal = world.propose(world.ana, message_id="msg_2").proposal
    revoked = world.memory.set_consent(world.ana, "s_1", {"consent": "revoked"})
    assert revoked.invalidated_proposals == 1 and len(world.store.for_user(world.ana)) == 1
    assert world.confirm(world.ana, proposal.proposal_id, expected=1).status == "CONSENT_REQUIRED"
    world.grant(world.ana)
    assert world.confirm(world.ana, proposal.proposal_id, expected=1).status == "PROPOSAL_STALE"
    assert world.writes.proposal(world.ana, proposal.proposal_id).state is ProposalState.INVALIDATED


def test_deleting_a_chain_removes_every_version_invalidates_proposals_and_keeps_counting(world):
    world.grant(world.ana)
    assert world.declare(world.ana, month="2026-06").ok and world.declare(world.ana, expected=1).ok
    proposal = world.propose(world.ana, message_id="msg_3").proposal
    (chain_id,) = {d.chain_id for d in world.store.for_user(world.ana)}
    world.grant(world.bea)
    assert world.declare(world.bea).ok
    assert world.memory.delete_chain(world.bea, "s_1", chain_id).status == "NOT_FOUND"  # another user's chain
    deleted = world.memory.delete_chain(world.ana, "s_1", chain_id)
    assert (deleted.status, deleted.deleted_versions, deleted.invalidated_proposals) == ("DONE", 2, 1)
    assert world.store.for_user(world.ana) == () and len(world.store.for_user(world.bea)) == 1
    assert world.confirm(world.ana, proposal.proposal_id, expected=2).status == "PROPOSAL_STALE"
    (event,) = world.events(AuditKind.MEMORY_DELETED)
    assert event.draft.detail == f"chain={chain_id} deleted_versions=2 invalidated_proposals=1 revision=3"
    assert world.declare(world.ana).ok and world.memory.consent(world.ana).memory_revision == 4  # never reset
    assert world.memory.delete_chain(world.ana, "s_1", chain_id).status == "NOT_FOUND"


def test_deletion_needs_no_consent(world):
    world.grant(world.ana)
    assert world.declare(world.ana).ok
    world.memory.set_consent(world.ana, "s_1", {"consent": "revoked"})
    (chain_id,) = {d.chain_id for d in world.store.for_user(world.ana)}
    assert world.memory.delete_chain(world.ana, "s_1", chain_id).ok and world.store.for_user(world.ana) == ()


# ---- concurrency ------------------------------------------------------------------------------------------

def _race(count: int, action) -> list[str]:
    barrier, results = threading.Barrier(count), []

    def run(index: int) -> None:
        barrier.wait()
        results.append(action(index).status)

    threads = [threading.Thread(target=run, args=(i,)) for i in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return sorted(results)


def test_concurrent_confirmations_of_one_proposal_write_once(world):
    world.grant(world.ana)
    proposal = world.propose(world.ana).proposal
    assert _race(6, lambda i: world.confirm(world.ana, proposal.proposal_id, amount=1_000_000 + i)) == ["DONE"] + ["PROPOSAL_USED"] * 5
    assert len(world.store.for_user(world.ana)) == 1 and len(world.events(AuditKind.MEMORY_CONFIRMED)) == 1


def test_concurrent_first_declarations_create_one_chain(world):
    world.grant(world.ana)
    assert _race(6, lambda i: world.declare(world.ana, amount=1_000_000 + i)) == ["DONE"] + ["VERSION_CONFLICT"] * 5
    assert len(world.store.for_user(world.ana)) == 1


def test_concurrent_edits_of_the_same_version_append_once(world):
    world.grant(world.ana)
    assert world.declare(world.ana).ok
    assert _race(6, lambda i: world.declare(world.ana, amount=1_000_000 + i, expected=1)) == ["DONE"] + ["VERSION_CONFLICT"] * 5
    assert [d.version for d in world.store.for_user(world.ana)] == [1, 2]


def _both(first, second) -> tuple:
    """Run two calls at the same moment; their results, in order."""
    barrier, results = threading.Barrier(2), [None, None]

    def run(index: int, call) -> None:
        barrier.wait()
        results[index] = call()

    threads = [threading.Thread(target=run, args=(0, first)), threading.Thread(target=run, args=(1, second))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return tuple(results)


def test_a_confirmation_racing_a_revocation_either_lands_before_it_or_not_at_all(world):
    for round_ in range(4):
        world.grant(world.ana)
        proposal = world.propose(world.ana, message_id=f"msg_{round_}").proposal
        expected = len(world.store.for_user(world.ana))
        confirmed, _ = _both(
            lambda p=proposal, e=expected: world.confirm(world.ana, p.proposal_id, expected=e).status,
            lambda: world.memory.set_consent(world.ana, "s_1", {"consent": "revoked"}).status,
        )
        stored = world.writes.proposal(world.ana, proposal.proposal_id)
        if confirmed == "DONE":
            assert stored.state is ProposalState.CONSUMED and len(world.store.for_user(world.ana)) == expected + 1
        else:
            assert confirmed == "CONSENT_REQUIRED" and stored.state is ProposalState.INVALIDATED
            assert len(world.store.for_user(world.ana)) == expected


def test_a_confirmation_racing_the_account_deletion_never_leaves_memory_behind(world):
    world.grant(world.ana)
    proposal = world.propose(world.ana).proposal
    session = world.services.accounts.resolve(world.ana_token)
    confirmed, deleted = _both(
        lambda: world.confirm(world.ana, proposal.proposal_id).status,
        lambda: world.services.accounts.delete_account(session, PASSWORD, "DELETE").status.value,
    )
    assert deleted == "DELETED" and confirmed in ("DONE", "NOT_WRITABLE")
    assert world.store.for_user(world.ana) == () and world.writes.proposal(world.ana, proposal.proposal_id) is None
    assert world.writes.state(world.ana).consent is Consent.MISSING
    # a request authenticated before the deletion, arriving late, recreates nothing
    assert world.confirm(world.ana, proposal.proposal_id).status == "NOT_FOUND"  # the proposal went with the account
    assert world.declare(world.ana).status == "NOT_WRITABLE"
    assert world.memory.set_consent(world.ana, "s_1", {"consent": "granted"}).status == "NOT_WRITABLE"
    assert world.store.for_user(world.ana) == () and world.writes.state(world.ana).consent is Consent.MISSING


def test_account_deletion_erases_every_memory_record_and_keeps_the_other_users(world):
    for user in (world.ana, world.bea):
        world.grant(user)
        assert world.declare(user).ok
        assert world.propose(user, message_id=f"msg_{user}").ok
    session = world.services.accounts.resolve(world.ana_token)
    erased = world.services.accounts.delete_account(session, PASSWORD, "DELETE").erased.counts
    assert (erased["user_memory"], erased["memory_state"], erased["memory_proposals"]) == (1, 1, 1)
    assert world.snapshot(world.ana)[:3] == ((), world.writes.state(world.ana), ())
    assert world.writes.state(world.ana).consent_generation == 0
    assert len(world.store.for_user(world.bea)) == 1 and world.writes.state(world.bea).granted
    assert len(world._proposals(world.bea)) == 1
    assert world.services.audit.verify().ok


def test_the_stored_proposal_holds_references_and_typed_values_never_message_text(world):
    world.grant(world.ana)
    proposal = world.propose(world.ana).proposal
    from neural_ledger.domain.memory.proposals import proposal_record

    record = proposal_record(proposal)
    assert set(record["origin"]) == {"kind", "session_id", "message_id"}
    assert not any("text" in key or "hash" in key for key in record)
    assert ProfileOrigin() not in (proposal.origin,)


def test_a_confirmation_racing_the_chain_deletion_never_restores_the_chain(world):
    for round_ in range(4):
        world.grant(world.ana)
        if not world.store.for_user(world.ana):
            assert world.declare(world.ana, month="2026-06").ok
        proposal = world.propose(world.ana, message_id=f"msg_del_{round_}").proposal
        (chain_id,) = {d.chain_id for d in world.store.for_user(world.ana)}
        confirmed, deleted = _both(
            lambda p=proposal: world.confirm(world.ana, p.proposal_id, expected=p.expected_version).status,
            lambda c=chain_id: world.memory.delete_chain(world.ana, "s_1", c).status,
        )
        assert deleted == "DONE"  # the chain existed either way, so the deletion always lands
        assert confirmed in ("DONE", "PROPOSAL_STALE")
        assert world.store.chain(world.ana, chain_id) == ()  # whatever the order, nothing of the chain survives
        assert world.confirm(world.ana, proposal.proposal_id, expected=proposal.expected_version).status in ("PROPOSAL_USED", "PROPOSAL_STALE")
        assert world.store.for_user(world.ana) == ()
