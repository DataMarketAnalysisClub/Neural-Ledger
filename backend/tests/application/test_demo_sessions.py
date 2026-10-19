"""Demo sessions open only allowlisted personas, through the same atomic session write as sign-in; and the
container wires one writes object over the same stores (memory) or one database (SQLite)."""

from __future__ import annotations

import json
import sqlite3
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
from neural_ledger.application.use_cases.accounts import DEMO_PERSONAS, AccountStatus, AccountUseCases
from neural_ledger.bootstrap import container
from neural_ledger.bootstrap.container import build
from neural_ledger.domain.audit.events import Actor, AuditKind, verify_chain
from neural_ledger.domain.finance.profile import RiskProfile
from neural_ledger.domain.user.account import token_digest
from neural_ledger.domain.user.profile import UserProfile
from tests.conftest import TEST_CIPHER, make_settings

NOW = datetime(2026, 10, 29, 9, tzinfo=UTC)
EMAIL = "demo@accounts.invalid"
PASSWORD = "synthetic-password-123"
PERSONAS = [UserProfile("camila", "Camila", "es", RiskProfile.MODERATE), UserProfile("diego", "Diego")]


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
        return f"demo-token-{self.count}"


class FailingAuditLog(InMemoryAuditLog):
    failing = False

    def append_all(self, drafts):
        if self.failing:
            raise RuntimeError("audit unavailable")
        return super().append_all(drafts)


@pytest.fixture(params=["memory", "sqlite"])
def world(request, tmp_path):
    if request.param == "memory":
        db = None
        accounts, sessions, inner, audit = InMemoryUserAccountStore(), InMemorySessionStore(), InMemoryUserProfileStore(), FailingAuditLog()
    else:
        db = SqliteDatabase(tmp_path / "demo-sessions.db")
        accounts, sessions, inner, audit = SqliteUserAccountStore(db, TEST_CIPHER), SqliteSessionStore(db), SqliteUserProfileStore(db, TEST_CIPHER), SqliteAuditLog(db, TEST_CIPHER)
    profiles = PersonaOverlayProfileStore(PERSONAS, inner)
    writes = InMemoryAccountWrites(accounts, sessions, profiles, audit) if db is None else SqliteAccountWrites(db, TEST_CIPHER)
    tokens = FakeTokens()
    use_cases = AccountUseCases(
        accounts, sessions, writes, FakeHasher(), tokens, FixedClock(NOW), SequentialIds(), demo_personas=frozenset(DEMO_PERSONAS)
    )
    return request.param, db, use_cases, sessions, audit, tokens


def _fail_audit(kind, db, audit):
    if kind == "memory":
        audit.failing = True
    else:
        db.connection.execute(
            "CREATE TEMP TRIGGER fail_audit BEFORE INSERT ON audit_events BEGIN SELECT RAISE(ABORT, 'audit unavailable'); END"
        )


@pytest.mark.parametrize("persona", DEMO_PERSONAS)
def test_allowlisted_persona_opens_a_token_hash_only_session(world, persona):
    _, _, use_cases, sessions, audit, _ = world
    outcome = use_cases.start_demo_session(persona)
    assert outcome.ok and outcome.session.user_id == persona
    token = outcome.session.token
    stored = sessions.by_token_hash(token_digest(token))
    assert stored is not None and stored.user_id == persona and stored.session_ref == outcome.session.session_ref
    assert stored.token_hash == token_digest(token) != token
    assert use_cases.resolve(token).user_id == persona
    event = audit.events()[-1]
    assert event.draft.kind is AuditKind.SESSION_STARTED and event.draft.actor is Actor.USER
    assert event.draft.user_id == persona and event.draft.session_id == outcome.session.session_ref
    assert event.draft.detail == "reason=demo_session"
    record = json.dumps(event.to_record())
    assert token not in record and "@" not in record
    assert verify_chain(audit.events()).ok


@pytest.mark.parametrize("persona", ["eve", "usr_000001", "CAMILA", "camila ", "", None, 7, ["camila"]])
def test_unlisted_persona_is_rejected_without_echo_or_session(world, persona):
    _, _, use_cases, _, audit, tokens = world
    before = audit.events()
    outcome = use_cases.start_demo_session(persona)
    assert outcome.status is AccountStatus.INVALID_INPUT and outcome.field == "persona" and outcome.session is None
    assert outcome.message == "choose an available demo persona"  # one constant message: the value is never echoed
    assert audit.events() == before and tokens.count == 0


def test_disabled_demo_sessions_reject_even_allowlisted_personas():
    use_cases = AccountUseCases(
        InMemoryUserAccountStore(), InMemorySessionStore(), None, FakeHasher(), FakeTokens(), FixedClock(NOW), SequentialIds()
    )
    assert use_cases.demo_personas == ()
    assert use_cases.start_demo_session("camila").status is AccountStatus.INVALID_INPUT


def test_only_allowlisted_personas_can_be_enabled():
    with pytest.raises(ValueError):
        AccountUseCases(
            InMemoryUserAccountStore(), InMemorySessionStore(), None, FakeHasher(), FakeTokens(), FixedClock(NOW), SequentialIds(),
            demo_personas=frozenset({"camila", "eve"}),
        )


def test_audit_failure_leaves_no_demo_session(world):
    kind, db, use_cases, _, audit, tokens = world
    before = audit.events()
    _fail_audit(kind, db, audit)
    with pytest.raises((RuntimeError, sqlite3.IntegrityError), match="audit unavailable"):
        use_cases.start_demo_session("camila")
    assert tokens.count == 1
    assert use_cases.resolve(f"demo-token-{tokens.count}") is None
    if kind == "memory":
        audit.failing = False
    else:
        db.connection.execute("DROP TRIGGER fail_audit")
    assert audit.events() == before


def test_data_source_is_persona_empty_or_sample(world):
    _, _, use_cases, _, _, _ = world
    assert use_cases.data_source("camila") == "persona"
    session = use_cases.signup(EMAIL, PASSWORD, "Ana").session
    assert use_cases.data_source(session.user_id) == "empty"
    assert use_cases.set_sample_data(session.user_id, session.session_ref, True).ok
    assert use_cases.data_source(session.user_id) == "sample"


# ---- container wiring ---------------------------------------------------------------------------


def test_demo_mode_builds_no_accounts_and_overlays_read_only_personas():
    services, _ = build(make_settings())
    assert services.auth.mode == "demo" and services.auth.demo_personas == ()
    assert services.accounts is None and services.profile_editing is None
    assert services.profiles.user_profile("camila").ok


def test_memory_accounts_mode_builds_one_writes_over_the_shared_stores(monkeypatch):
    built = []

    class Counting(InMemoryAccountWrites):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            built.append(self)

    monkeypatch.setattr(container, "InMemoryAccountWrites", Counting)
    services, adapters = build(make_settings(auth="accounts"))
    assert len(built) == 1
    writes = built[0]
    assert services.accounts._writes is writes and services.profile_editing._writes is writes
    assert writes._audit is adapters.audit_log
    assert writes._profiles is services.profile_editing._profiles is services.profiles._profiles is services.financial._profiles
    assert services.accounts._accounts is writes._accounts and services.accounts._sessions is writes._sessions
    assert adapters.audit_log._lock is writes._accounts._lock  # the one lock every account write and audit append takes
    assert services.auth.demo_personas == DEMO_PERSONAS


def test_sqlite_accounts_mode_shares_one_database(tmp_path):
    services, adapters = build(make_settings(auth="accounts", persistence="sqlite", sqlite_path=str(tmp_path / "wiring.db")))
    writes = services.accounts._writes
    assert isinstance(writes, SqliteAccountWrites) and services.profile_editing._writes is writes
    db = writes._db
    profiles = services.profiles._profiles
    assert isinstance(profiles, PersonaOverlayProfileStore) and isinstance(profiles._inner, SqliteUserProfileStore)
    for store in (services.accounts._accounts, services.accounts._sessions, adapters.audit_log, profiles._inner, adapters.actions_repo):
        assert store._db is db


def test_disabled_demo_personas_setting_disables_demo_sessions():
    services, _ = build(make_settings(auth="accounts", demo_personas=False))
    assert services.auth.demo_personas == () and services.accounts.demo_personas == ()
