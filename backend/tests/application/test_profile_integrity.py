"""A profile change and its PROFILE_UPDATED event commit together or not at all (memory and SQLite)."""

import sqlite3
import threading
from dataclasses import dataclass, replace
from datetime import UTC, datetime

import pytest

from neural_ledger.adapters.outbound.persistence.memory import (
    InMemoryAccountWrites,
    InMemoryAuditLog,
    InMemorySessionStore,
    InMemoryUserAccountStore,
    InMemoryUserProfileStore,
)
from neural_ledger.adapters.outbound.persistence.overlay import PersonaOverlayProfileStore
from neural_ledger.adapters.outbound.persistence.sqlite import (
    SqliteAccountWrites,
    SqliteAuditLog,
    SqliteDatabase,
    SqliteSessionStore,
    SqliteUserAccountStore,
    SqliteUserProfileStore,
)
from neural_ledger.adapters.outbound.system.clock import FixedClock
from neural_ledger.adapters.outbound.system.ids import SequentialIds
from neural_ledger.application.ports import IdCollision, ProfileWrites
from neural_ledger.application.use_cases.accounts import AccountUseCases
from neural_ledger.application.use_cases.profile import ProfileEditing
from neural_ledger.domain.audit.events import Actor, AuditDraft, AuditKind, verify_chain
from neural_ledger.domain.finance.profile import RiskProfile
from neural_ledger.domain.user.profile import QuestionnaireAnswer, UserProfile
from neural_ledger.domain.user.questionnaire import CURRENT_VERSION, REGISTRY

NOW = datetime(2026, 10, 29, 9, tzinfo=UTC)
PARAMS = "fc-0.1"
EMAIL = "ana@example.com"
PASSWORD = "correct horse battery"
PERSONA = UserProfile("camila", "Camila", "es", RiskProfile.MODERATE)
AUDIT_DOWN = (RuntimeError, sqlite3.IntegrityError)


class FakeHasher:
    def hash(self, password: str) -> str:
        return f"scrypt$fake${password[::-1]}"

    def verify(self, password: str, encoded: str | None) -> bool:
        return encoded == self.hash(password)


class FakeTokens:
    def __init__(self) -> None:
        self.count = 0

    def new_token(self) -> str:
        self.count += 1
        return f"token-{self.count}"


class FailingAuditLog(InMemoryAuditLog):
    failing = False

    def append(self, draft):
        if self.failing:
            raise RuntimeError("audit unavailable")
        return super().append(draft)

    def append_all(self, drafts):
        if self.failing:
            raise RuntimeError("audit unavailable")
        return super().append_all(drafts)


class ReusedIds:
    """Hands out an event id that is already on the chain."""

    def __init__(self, event_id: str) -> None:
        self._event_id = event_id

    def new(self, prefix: str) -> str:
        return self._event_id


class StaleReads:
    """Answers with a snapshot read before a concurrent edit; writes still reach the real store."""

    def __init__(self, store, snapshot: UserProfile) -> None:
        self._store = store
        self._snapshot = snapshot

    def get(self, user_id: str) -> UserProfile | None:
        return self._snapshot if user_id == self._snapshot.user_id else self._store.get(user_id)

    def put(self, profile: UserProfile) -> None:
        self._store.put(profile)


@dataclass
class World:
    kind: str
    db: SqliteDatabase | None
    profiles: PersonaOverlayProfileStore
    audit: object
    writes: object
    ids: SequentialIds
    user_id: str
    session_ref: str


def _editing(world: World, ids=None, profiles=None) -> ProfileEditing:
    """The only seam that changes when ProfileEditing commits through ProfileWrites."""
    return ProfileEditing(profiles or world.profiles, world.writes, FixedClock(NOW), ids or world.ids, PARAMS)


def _answers(option: int) -> tuple[QuestionnaireAnswer, ...]:
    return tuple(QuestionnaireAnswer(q.question_id, q.options[option].option_id) for q in REGISTRY[CURRENT_VERSION].questions)


def _rename(editing: ProfileEditing, user_id: str, session_id: str):
    return editing.update_profile(user_id, session_id, display_name="Beatriz", language="pt")


def _aggressive(editing: ProfileEditing, user_id: str, session_id: str):
    return editing.submit_questionnaire(user_id, session_id, CURRENT_VERSION, _answers(2))


EDITS = pytest.mark.parametrize("edit", [_rename, _aggressive], ids=["name_language", "questionnaire"])


@pytest.fixture(params=["memory", "sqlite"])
def world(request, tmp_path) -> World:
    if request.param == "memory":
        db = None
        accounts, sessions, inner, audit = InMemoryUserAccountStore(), InMemorySessionStore(), InMemoryUserProfileStore(), FailingAuditLog()
    else:
        db = SqliteDatabase(tmp_path / "profile-integrity.db")
        accounts, sessions, inner, audit = SqliteUserAccountStore(db), SqliteSessionStore(db), SqliteUserProfileStore(db), SqliteAuditLog(db)
    profiles = PersonaOverlayProfileStore([PERSONA], inner)
    writes = InMemoryAccountWrites(accounts, sessions, profiles, audit) if db is None else SqliteAccountWrites(db)
    ids = SequentialIds()
    accounts_use_cases = AccountUseCases(accounts, sessions, writes, FakeHasher(), FakeTokens(), FixedClock(NOW), ids)
    session = accounts_use_cases.signup(EMAIL, PASSWORD, "Ana").session
    built = World(request.param, db, profiles, audit, writes, ids, session.user_id, session.session_ref)
    assert _editing(built).submit_questionnaire(session.user_id, session.session_ref, CURRENT_VERSION, _answers(0)).ok
    prior = profiles.get(session.user_id)
    assert prior.questionnaire_version == CURRENT_VERSION and prior.declared_tolerance is not RiskProfile.AGGRESSIVE
    assert prior.display_name == "Ana" and prior.language != "pt"
    return built


def _fail_audit(world: World) -> None:
    if world.kind == "memory":
        world.audit.failing = True
    else:
        world.db.connection.execute(
            "CREATE TEMP TRIGGER fail_audit BEFORE INSERT ON audit_events "
            "BEGIN SELECT RAISE(ABORT, 'audit unavailable'); END"
        )


def _restore_audit(world: World) -> None:
    if world.kind == "memory":
        world.audit.failing = False
    else:
        world.db.connection.execute("DROP TRIGGER fail_audit")


def _draft(event_id: str, user_id: str, session_id: str) -> AuditDraft:
    return AuditDraft(
        event_id=event_id, timestamp=NOW, session_id=session_id, user_id=user_id,
        actor=Actor.USER, kind=AuditKind.PROFILE_UPDATED, detail="fields=display_name",
    )


@EDITS
def test_p1_audit_failure_leaves_profile_and_chain_unchanged(world, edit):
    prior = world.profiles.get(world.user_id)
    before = world.audit.events()
    _fail_audit(world)
    with pytest.raises(AUDIT_DOWN, match="audit unavailable"):
        edit(_editing(world), world.user_id, world.session_ref)
    after = world.profiles.get(world.user_id)
    assert after == prior
    assert (after.display_name, after.language) == (prior.display_name, prior.language)
    assert (after.declared_tolerance, after.questionnaire_version, after.questionnaire) == (
        prior.declared_tolerance, prior.questionnaire_version, prior.questionnaire,
    )
    assert world.audit.events() == before
    _restore_audit(world)
    assert verify_chain(world.audit.events()).ok


@EDITS
def test_p2_retry_after_audit_failure_commits_once_and_keeps_the_chain(world, edit):
    before = world.audit.events()
    _fail_audit(world)
    with pytest.raises(AUDIT_DOWN, match="audit unavailable"):
        edit(_editing(world), world.user_id, world.session_ref)
    _restore_audit(world)
    assert edit(_editing(world), world.user_id, world.session_ref).ok
    events = world.audit.events()
    assert events[: len(before)] == before and len(events) == len(before) + 1
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    assert verify_chain(events).ok


@EDITS
def test_p3_reused_event_id_raises_and_changes_nothing(world, edit):
    prior = world.profiles.get(world.user_id)
    before = world.audit.events()
    reused = ReusedIds(before[-1].draft.event_id)
    with pytest.raises(IdCollision):
        edit(_editing(world, ids=reused), world.user_id, world.session_ref)
    assert world.profiles.get(world.user_id) == prior
    assert world.audit.events() == before
    assert verify_chain(world.audit.events()).ok


@EDITS
def test_p4_stale_snapshot_is_rejected_without_losing_the_concurrent_edit(world, edit):
    stale = world.profiles.get(world.user_id)
    assert _editing(world).update_profile(world.user_id, world.session_ref, display_name="Carla").ok
    current = world.profiles.get(world.user_id)
    before = world.audit.events()
    outcome = edit(_editing(world, profiles=StaleReads(world.profiles, stale)), world.user_id, world.session_ref)
    assert outcome.status.value == "INVALID_INPUT"
    assert world.profiles.get(world.user_id) == current
    assert world.audit.events() == before


@EDITS
def test_p5_persona_behind_the_overlay_never_changes(world, edit):
    before = world.audit.events()
    outcome = edit(_editing(world), PERSONA.user_id, world.session_ref)
    assert outcome.status.value == "INVALID_INPUT"
    assert world.profiles.get(PERSONA.user_id) == PERSONA
    assert world.audit.events() == before


@EDITS
def test_p6_success_appends_exactly_one_private_profile_event(world, edit):
    before = world.audit.events()
    outcome = edit(_editing(world), world.user_id, world.session_ref)
    assert outcome.ok
    events = world.audit.events()
    assert events[: len(before)] == before and len(events) == len(before) + 1
    draft = events[-1].draft
    assert draft.kind is AuditKind.PROFILE_UPDATED and draft.actor is Actor.USER
    assert draft.user_id == world.user_id and draft.session_id == world.session_ref
    assert all(secret not in (draft.detail or "") for secret in ("Ana", "Beatriz", EMAIL, "@"))
    assert verify_chain(events).ok


def test_p7_both_account_writes_adapters_are_profile_writes(world):
    assert isinstance(world.writes, ProfileWrites)


@pytest.mark.parametrize("mismatch", ["updated", "event"])
def test_p8_owner_mismatch_raises_and_changes_nothing(world, mismatch):
    prior = world.profiles.get(world.user_id)
    before = world.audit.events()
    updated = replace(prior, display_name="Beatriz")
    if mismatch == "updated":
        updated = replace(updated, user_id="usr_999999")
    owner = "usr_999999" if mismatch == "event" else world.user_id
    with pytest.raises(ValueError):
        world.writes.update_profile(prior, updated, (_draft("evt_direct_1", owner, world.session_ref),))
    assert world.profiles.get(world.user_id) == prior
    assert world.profiles.get("usr_999999") is None
    assert world.audit.events() == before


def test_p9_stale_or_persona_expected_returns_false_without_writes(world):
    prior = world.profiles.get(world.user_id)
    before = world.audit.events()
    stale = replace(prior, display_name="Zoe")
    assert world.writes.update_profile(stale, replace(prior, language="pt"), (_draft("evt_direct_1", world.user_id, world.session_ref),)) is False
    persona = replace(PERSONA, display_name="Mallory")
    assert world.writes.update_profile(PERSONA, persona, (_draft("evt_direct_2", PERSONA.user_id, world.session_ref),)) is False
    assert world.profiles.get(world.user_id) == prior
    assert world.profiles.get(PERSONA.user_id) == PERSONA
    assert world.audit.events() == before


def test_p10_update_profile_commits_without_deadlock(world):
    prior = world.profiles.get(world.user_id)
    updated = replace(prior, display_name="Beatriz")
    before = world.audit.events()
    results: list[object] = []

    def run() -> None:
        try:
            results.append(world.writes.update_profile(prior, updated, (_draft("evt_direct_1", world.user_id, world.session_ref),)))
        except Exception as error:  # reported below; a thread swallows it otherwise
            results.append(error)

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(5)
    assert not worker.is_alive(), "update_profile did not return within 5s"
    assert results == [True]
    assert world.profiles.get(world.user_id) == updated
    events = world.audit.events()
    assert len(events) == len(before) + 1 and events[-1].draft.event_id == "evt_direct_1"
    assert verify_chain(events).ok
