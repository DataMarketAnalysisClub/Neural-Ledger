import sqlite3
import threading
from dataclasses import replace
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
from neural_ledger.application.ports import AccountWrites, IdCollision
from neural_ledger.domain.audit.events import Actor, AuditDraft, AuditKind, verify_chain
from neural_ledger.domain.user.account import Session, UserAccount, token_digest
from neural_ledger.domain.user.profile import UserProfile

NOW = datetime(2026, 10, 29, 9, tzinfo=UTC)
HASH = "scrypt$fake$hash"


class FailingAudit(InMemoryAuditLog):
    failing = False

    def append_all(self, drafts):
        if self.failing:
            raise RuntimeError("audit unavailable")
        return super().append_all(drafts)


@pytest.fixture(params=["memory", "sqlite"])
def world(request, tmp_path):
    if request.param == "memory":
        db = None
        accounts, sessions, profiles, audit = (
            InMemoryUserAccountStore(), InMemorySessionStore(), InMemoryUserProfileStore(), FailingAudit()
        )
        writes = InMemoryAccountWrites(accounts, sessions, profiles, audit)
    else:
        db = SqliteDatabase(tmp_path / "writes.db")
        accounts, sessions, profiles, audit = (
            SqliteUserAccountStore(db), SqliteSessionStore(db), SqliteUserProfileStore(db), SqliteAuditLog(db)
        )
        writes = SqliteAccountWrites(db)
    return request.param, db, accounts, sessions, profiles, audit, writes


def _values(index=1, email="ana@example.com", user_id=None, session_ref=None, token=None, event_ids=None):
    owner = user_id or f"usr_{index:06d}"
    session = Session.open(session_ref or f"sess_{index:06d}", owner, token_digest(token or f"secret-{index}"), NOW)
    ids = event_ids or (f"evt_{index:06d}a", f"evt_{index:06d}b")
    events = tuple(AuditDraft(event_id=event_id, timestamp=NOW, session_id=session.session_ref, user_id=owner,
                              actor=Actor.USER, kind=kind) for event_id, kind in zip(
                                  ids, (AuditKind.USER_REGISTERED, AuditKind.SESSION_STARTED), strict=True
                              ))
    return UserAccount(owner, email, HASH, NOW), UserProfile(owner, "Ana"), session, events


def _state(world):
    _, db, accounts, sessions, profiles, audit, _ = world
    if db is not None:
        return tuple(db.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in (
            "user_accounts", "user_profiles", "sessions", "audit_events"
        )), audit.events()
    return (len(accounts._accounts), len(profiles._profiles), len(sessions._sessions), len(audit.events())), audit.events()


def test_register_commits_every_row_and_a_verifiable_chain(world):
    _, _, accounts, sessions, profiles, audit, writes = world
    account, profile, session, events = _values()
    assert isinstance(writes, AccountWrites)
    assert writes.register(account, profile, session, events) is True
    assert accounts.get(account.user_id) == account
    assert profiles.get(account.user_id) == profile
    assert sessions.by_token_hash(session.token_hash) == session
    assert [e.draft for e in audit.events()] == list(events)
    assert verify_chain(audit.events()).ok


def test_duplicate_email_does_not_write(world):
    *_, writes = world
    assert writes.register(*_values())
    before = _state(world)
    assert writes.register(*_values(2, email="ana@example.com")) is False
    assert _state(world) == before


@pytest.mark.parametrize("collision", ["user", "profile", "session_ref", "token_hash", "first_event", "second_event"])
def test_generated_collision_preserves_existing_state(world, collision):
    _, _, accounts, _, profiles, _, writes = world
    first = _values()
    if collision == "profile":
        profiles.put(first[1])
    else:
        assert writes.register(*first)
    before = _state(world)
    next_values = _values(2, email="other@example.com")
    account, profile, session, events = next_values
    if collision in ("user", "profile"):
        account = replace(account, user_id=first[0].user_id)
        profile = replace(profile, user_id=account.user_id)
        session = replace(session, user_id=account.user_id)
        events = tuple(replace(e, user_id=account.user_id) for e in events)
    elif collision == "session_ref":
        session = replace(session, session_ref=first[2].session_ref)
    elif collision == "token_hash":
        session = replace(session, token_hash=first[2].token_hash)
    elif collision == "first_event":
        events = (replace(events[0], event_id=first[3][0].event_id), events[1])
    else:
        events = (events[0], replace(events[1], event_id=first[3][1].event_id))
    with pytest.raises(IdCollision):
        writes.register(account, profile, session, events)
    assert _state(world) == before
    assert accounts.by_email("other@example.com") is None
    assert profiles.get(first[0].user_id) == first[1]


def test_mismatched_owners_fail_before_writing(world):
    *_, writes = world
    account, profile, session, events = _values()
    with pytest.raises(ValueError, match="ownership mismatch"):
        writes.register(account, replace(profile, user_id="other"), session, events)
    assert _state(world)[0] == (0, 0, 0, 0)


@pytest.mark.parametrize("boundary", ["user_accounts", "user_profiles", "sessions", "first_event", "second_event"])
def test_sqlite_failure_at_each_insert_rolls_back_and_allows_retry(tmp_path, boundary):
    db = SqliteDatabase(tmp_path / "fail.db")
    writes, audit = SqliteAccountWrites(db), SqliteAuditLog(db)
    first = _values()
    assert writes.register(*first)
    prior = audit.events()
    table = "audit_events" if "event" in boundary else boundary
    condition = " WHEN NEW.sequence = 4" if boundary == "second_event" else ""
    db.connection.execute(
        f"CREATE TEMP TRIGGER fail_write BEFORE INSERT ON {table}{condition} "
        "BEGIN SELECT RAISE(ABORT, 'injected failure'); END"
    )
    with pytest.raises(sqlite3.IntegrityError, match="injected failure"):
        writes.register(*_values(2, email="other@example.com"))
    assert db.connection.in_transaction is False
    assert [db.connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] for name in (
        "user_accounts", "user_profiles", "sessions", "audit_events"
    )] == [1, 1, 1, 2]
    assert audit.events() == prior and verify_chain(audit.events()).ok
    db.connection.execute("DROP TRIGGER fail_write")
    assert writes.register(*_values(2, email="other@example.com"))
    assert audit.events()[2].sequence == prior[-1].sequence + 1
    assert audit.events()[2].prev_hash == prior[-1].event_hash
    assert verify_chain(audit.events()).ok


def test_memory_audit_failure_rolls_back_every_store_and_retries():
    accounts, sessions, profiles, audit = (
        InMemoryUserAccountStore(), InMemorySessionStore(), InMemoryUserProfileStore(), FailingAudit()
    )
    writes = InMemoryAccountWrites(accounts, sessions, profiles, audit)
    world = ("memory", None, accounts, sessions, profiles, audit, writes)
    assert writes.register(*_values())
    before = _state(world)
    audit.failing = True
    with pytest.raises(RuntimeError, match="audit unavailable"):
        writes.register(*_values(2, email="other@example.com"))
    assert _state(world) == before
    assert accounts.by_email("other@example.com") is None
    assert profiles.get("usr_000002") is None
    assert sessions.by_token_hash(token_digest("secret-2")) is None
    audit.failing = False
    assert writes.register(*_values(2, email="other@example.com"))
    assert audit.events()[2].prev_hash == before[1][-1].event_hash
    assert verify_chain(audit.events()).ok


@pytest.mark.parametrize("boundary", ["profile", "account", "session", "audit_after_publish"])
def test_memory_partial_write_exception_restores_all_state(monkeypatch, boundary):
    accounts, sessions, profiles, audit = (
        InMemoryUserAccountStore(), InMemorySessionStore(), InMemoryUserProfileStore(), FailingAudit()
    )
    writes = InMemoryAccountWrites(accounts, sessions, profiles, audit)
    assert writes.register(*_values())
    world = ("memory", None, accounts, sessions, profiles, audit, writes)
    before = _state(world)
    target, method = {
        "profile": (profiles, "put"),
        "account": (accounts, "add"),
        "session": (sessions, "add"),
        "audit_after_publish": (audit, "append_all"),
    }[boundary]
    original = getattr(target, method)

    def fail_after_write(*args):
        original(*args)
        raise RuntimeError("injected failure")

    with monkeypatch.context() as patch:
        patch.setattr(target, method, fail_after_write)
        with pytest.raises(RuntimeError, match="injected failure"):
            writes.register(*_values(2, email="other@example.com"))
    assert _state(world) == before
    assert writes.register(*_values(2, email="other@example.com"))
    assert audit.events()[2].prev_hash == before[1][-1].event_hash
    assert verify_chain(audit.events()).ok


def test_memory_readers_cannot_observe_a_write_before_audit_commits(monkeypatch):
    accounts, sessions, profiles, audit = (
        InMemoryUserAccountStore(), InMemorySessionStore(), InMemoryUserProfileStore(), FailingAudit()
    )
    writes = InMemoryAccountWrites(accounts, sessions, profiles, audit)
    entered, release, reader_started, reader_done = (
        threading.Event(), threading.Event(), threading.Event(), threading.Event()
    )
    original = audit.append_all

    def blocked(drafts):
        entered.set()
        assert release.wait(timeout=5)
        return original(drafts)

    monkeypatch.setattr(audit, "append_all", blocked)
    registration = threading.Thread(target=lambda: writes.register(*_values()))
    registration.start()
    try:
        assert entered.wait(timeout=5)
        observed = []

        def read():
            reader_started.set()
            observed.append((accounts.by_email("ana@example.com"), profiles.get("usr_000001"),
                             sessions.by_token_hash(token_digest("secret-1")), audit.events()))
            reader_done.set()

        reader = threading.Thread(target=read)
        reader.start()
        assert reader_started.wait(timeout=5)
        assert not reader_done.is_set()
    finally:
        release.set()
        registration.join(timeout=5)
    reader.join(timeout=5)
    assert reader_done.is_set()
    assert observed[0][0] is not None and observed[0][1] is not None and observed[0][2] is not None
    assert len(observed[0][3]) == 2


def test_other_mutations_require_audit_and_preserve_preconditions(world):
    kind, db, accounts, sessions, _, audit, writes = world
    account, profile, session, events = _values()
    assert writes.register(account, profile, session, events)
    next_session = Session.open("sess_000099", account.user_id, token_digest("next-token"), NOW)
    draft = replace(events[1], event_id="evt_open", session_id=next_session.session_ref)
    before = audit.events()
    if kind == "memory":
        audit.failing = True
    else:
        db.connection.execute("CREATE TEMP TRIGGER fail_audit BEFORE INSERT ON audit_events "
                              "BEGIN SELECT RAISE(ABORT, 'audit unavailable'); END")
    with pytest.raises((RuntimeError, sqlite3.IntegrityError), match="audit unavailable"):
        writes.open_session(next_session, (draft,))
    assert sessions.by_token_hash(next_session.token_hash) is None
    with pytest.raises((RuntimeError, sqlite3.IntegrityError), match="audit unavailable"):
        writes.close_session(session, NOW, (replace(draft, event_id="evt_close"),))
    assert sessions.by_token_hash(session.token_hash).revoked_at is None
    with pytest.raises((RuntimeError, sqlite3.IntegrityError), match="audit unavailable"):
        writes.set_sample_data(account.user_id, True, (replace(draft, event_id="evt_flag"),))
    assert accounts.get(account.user_id).sample_data is False
    assert audit.events() == before
    if kind == "memory":
        audit.failing = False
    else:
        db.connection.execute("DROP TRIGGER fail_audit")
    assert writes.open_session(next_session, (draft,)) is None
    assert writes.close_session(session, NOW, (replace(draft, event_id="evt_close"),)) is True
    assert writes.set_sample_data(account.user_id, True, (replace(draft, event_id="evt_flag"),)) is True
    assert writes.close_session(session, NOW, (replace(draft, event_id="evt_unused"),)) is False
    assert writes.set_sample_data("usr_unknown", True, (replace(draft, event_id="evt_unused"),)) is False
    assert len(audit.events()) == len(before) + 3 and verify_chain(audit.events()).ok


def test_concurrent_register_of_one_email_commits_once(world):
    _, _, accounts, _, _, audit, writes = world
    barrier = threading.Barrier(8)
    results = []

    def register(index):
        barrier.wait()
        results.append(writes.register(*_values(index, email="race@example.com")))

    threads = [threading.Thread(target=register, args=(index,)) for index in range(1, 9)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(results) == [False] * 7 + [True]
    assert accounts.by_email("race@example.com") is not None
    assert len(audit.events()) == 2 and verify_chain(audit.events()).ok
