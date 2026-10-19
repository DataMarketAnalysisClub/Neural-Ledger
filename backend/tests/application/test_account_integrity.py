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
from neural_ledger.adapters.outbound.system.password import ScryptHasher
from neural_ledger.adapters.outbound.system.tokens import SecretsTokens
from neural_ledger.application.ports import IdCollision
from neural_ledger.application.use_cases.accounts import AccountUseCases
from neural_ledger.domain.audit.events import verify_chain
from neural_ledger.domain.user.account import token_digest
from tests.conftest import TEST_CIPHER

NOW = datetime(2026, 10, 29, 9, tzinfo=UTC)
PASSWORD = "correct horse battery"
EMAIL = "ana@example.com"


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


@pytest.fixture(params=["memory", "sqlite"])
def world(request, tmp_path):
    if request.param == "memory":
        accounts = InMemoryUserAccountStore()
        sessions = InMemorySessionStore()
        profiles = InMemoryUserProfileStore()
        audit = FailingAuditLog()
        db = None
    else:
        db = SqliteDatabase(tmp_path / "integrity.db")
        accounts = SqliteUserAccountStore(db, TEST_CIPHER)
        sessions = SqliteSessionStore(db)
        profiles = SqliteUserProfileStore(db, TEST_CIPHER)
        audit = SqliteAuditLog(db, TEST_CIPHER)
    writes = InMemoryAccountWrites(accounts, sessions, profiles, audit) if db is None else SqliteAccountWrites(db, TEST_CIPHER)
    use_cases = AccountUseCases(accounts, sessions, writes, FakeHasher(), FakeTokens(), FixedClock(NOW), SequentialIds())
    return request.param, db, accounts, sessions, profiles, audit, use_cases


def _failure(kind, db, audit):
    if kind == "memory":
        audit.failing = True
    else:
        db.connection.execute(
            "CREATE TEMP TRIGGER fail_audit BEFORE INSERT ON audit_events "
            "BEGIN SELECT RAISE(ABORT, 'audit unavailable'); END"
        )


def _restore(kind, db, audit):
    if kind == "memory":
        audit.failing = False
    else:
        db.connection.execute("DROP TRIGGER fail_audit")


def test_u1_reused_ids_never_overwrite_a_profile(world, tmp_path):
    kind, db, accounts, sessions, profiles, audit, use_cases = world
    first = use_cases.signup(EMAIL, PASSWORD, "Ana").session
    prior = profiles.get(first.user_id)
    before = audit.events()
    if kind == "sqlite":
        db.connection.close()
        db = SqliteDatabase(tmp_path / "integrity.db")
        accounts = SqliteUserAccountStore(db, TEST_CIPHER)
        sessions = SqliteSessionStore(db)
        profiles = SqliteUserProfileStore(db, TEST_CIPHER)
        audit = SqliteAuditLog(db, TEST_CIPHER)
    writes = InMemoryAccountWrites(accounts, sessions, profiles, audit) if db is None else SqliteAccountWrites(db, TEST_CIPHER)
    second = AccountUseCases(accounts, sessions, writes, FakeHasher(), FakeTokens(), FixedClock(NOW), SequentialIds())
    with pytest.raises(IdCollision):
        second.signup("other@example.com", PASSWORD, "Other")
    assert profiles.get(first.user_id) == prior
    assert accounts.by_email("other@example.com") is None
    assert audit.events() == before


def test_u2_signup_audit_failure_leaves_no_state(world):
    kind, db, accounts, sessions, profiles, audit, use_cases = world
    _failure(kind, db, audit)
    with pytest.raises((RuntimeError, sqlite3.IntegrityError), match="audit unavailable"):
        use_cases.signup(EMAIL, PASSWORD, "Ana")
    assert accounts.by_email(EMAIL) is None
    assert profiles.get("usr_000001") is None
    assert sessions.by_token_hash(token_digest("token-1")) is None
    assert audit.events() == ()


def test_u3_signin_audit_failure_leaves_no_session(world):
    kind, db, _, sessions, _, audit, use_cases = world
    use_cases.signup(EMAIL, PASSWORD, "Ana")
    before = audit.events()
    _failure(kind, db, audit)
    with pytest.raises((RuntimeError, sqlite3.IntegrityError), match="audit unavailable"):
        use_cases.signin(EMAIL, PASSWORD)
    assert sessions.by_token_hash(token_digest("token-2")) is None
    assert audit.events() == before


def test_u4_signout_audit_failure_preserves_active_session(world):
    kind, db, _, _, _, audit, use_cases = world
    first = use_cases.signup(EMAIL, PASSWORD, "Ana").session
    before = audit.events()
    _failure(kind, db, audit)
    with pytest.raises((RuntimeError, sqlite3.IntegrityError), match="audit unavailable"):
        use_cases.signout(first.token)
    assert use_cases.resolve(first.token) is not None
    assert audit.events() == before


def test_u5_sample_audit_failure_preserves_flag(world):
    kind, db, accounts, _, _, audit, use_cases = world
    first = use_cases.signup(EMAIL, PASSWORD, "Ana").session
    before = audit.events()
    _failure(kind, db, audit)
    with pytest.raises((RuntimeError, sqlite3.IntegrityError), match="audit unavailable"):
        use_cases.set_sample_data(first.user_id, first.session_ref, True)
    assert accounts.get(first.user_id).sample_data is False
    assert audit.events() == before
    _restore(kind, db, audit)
    assert use_cases.set_sample_data(first.user_id, first.session_ref, True).ok
    assert verify_chain(audit.events()).ok


def test_u6_retry_signup_after_audit_failure_preserves_chain(world):
    kind, db, accounts, _, profiles, audit, use_cases = world
    _failure(kind, db, audit)
    with pytest.raises((RuntimeError, sqlite3.IntegrityError), match="audit unavailable"):
        use_cases.signup(EMAIL, PASSWORD, "Ana")
    _restore(kind, db, audit)
    outcome = use_cases.signup(EMAIL, PASSWORD, "Ana")
    assert outcome.ok and accounts.by_email(EMAIL).user_id == outcome.session.user_id
    assert profiles.get(outcome.session.user_id).display_name == "Ana"
    assert [event.sequence for event in audit.events()] == [1, 2]
    assert verify_chain(audit.events()).ok


def test_u7_sqlite_real_secrets_never_appear_in_persistence(tmp_path):
    db = SqliteDatabase(tmp_path / "privacy.db")
    accounts, sessions, audit = SqliteUserAccountStore(db, TEST_CIPHER), SqliteSessionStore(db), SqliteAuditLog(db, TEST_CIPHER)
    use_cases = AccountUseCases(
        accounts, sessions, SqliteAccountWrites(db, TEST_CIPHER), ScryptHasher(), SecretsTokens(), FixedClock(NOW), SequentialIds()
    )
    first = use_cases.signup(EMAIL, PASSWORD, "Secret Name").session
    second = use_cases.signin(EMAIL, PASSWORD).session
    assert use_cases.signout(second.token)
    dump = "\n".join(db.connection.iterdump())
    records = "\n".join(row[0] for row in db.connection.execute("SELECT record FROM audit_events"))
    for secret in (PASSWORD, first.token, second.token):
        assert secret not in dump
    assert EMAIL not in records and "Secret Name" not in records
    assert EMAIL not in dump and "Secret Name" not in dump  # option B: the email is sealed and searched by its blind index
    assert verify_chain(audit.events()).ok


def test_u8_collision_error_never_exposes_personal_data(world):
    kind, db, accounts, sessions, profiles, audit, use_cases = world
    first = use_cases.signup(EMAIL, PASSWORD, "Secret Name").session
    second = AccountUseCases(
        accounts, sessions, InMemoryAccountWrites(accounts, sessions, profiles, audit) if db is None else SqliteAccountWrites(db, TEST_CIPHER),
        FakeHasher(), FakeTokens(), FixedClock(NOW), SequentialIds()
    )
    with pytest.raises(IdCollision) as error:
        second.signup("other@example.com", PASSWORD, "Other Name")
    assert all(secret not in str(error.value) for secret in (EMAIL, "other@example.com", "Secret Name", "Other Name", PASSWORD, first.token))
