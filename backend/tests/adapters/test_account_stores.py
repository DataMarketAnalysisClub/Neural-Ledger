"""One account/session store suite run against the in-memory and SQLite adapters."""

import threading
from datetime import UTC, datetime, timedelta

import pytest

from neural_ledger.adapters.outbound.persistence.memory import InMemorySessionStore, InMemoryUserAccountStore
from neural_ledger.adapters.outbound.persistence.sqlite import SqliteDatabase, SqliteSessionStore, SqliteUserAccountStore
from neural_ledger.application.ports import SessionStore, UserAccountStore
from neural_ledger.domain.user.account import Session, UserAccount, token_digest

NOW = datetime(2026, 10, 29, 9, tzinfo=UTC)
HASH = "scrypt$16384$8$1$c2FsdHNhbHRzYWx0c2FsdA==$aGFzaGhhc2hoYXNoaGFzaA=="
TOKEN = "plain-session-token-never-stored"


@pytest.fixture(params=["memory", "sqlite"])
def stores(request, tmp_path):
    if request.param == "memory":
        return InMemoryUserAccountStore(), InMemorySessionStore()
    db = SqliteDatabase(tmp_path / "accounts.db")
    return SqliteUserAccountStore(db), SqliteSessionStore(db)


def _account(user_id="usr_000001", email="ana@example.com") -> UserAccount:
    return UserAccount(user_id, email, HASH, NOW)


def _session(ref="sess_000001", token=TOKEN, user_id="usr_000001") -> Session:
    return Session.open(ref, user_id, token_digest(token), NOW)


def test_stores_satisfy_their_ports(stores):
    accounts, sessions = stores
    assert isinstance(accounts, UserAccountStore) and isinstance(sessions, SessionStore)


def test_account_round_trip_and_unique_email_and_id(stores):
    accounts, _ = stores
    account = _account()
    assert accounts.add(account) is True
    assert accounts.get("usr_000001") == account and accounts.by_email("ana@example.com") == account
    assert accounts.add(_account("usr_000002", "ana@example.com")) is False
    assert accounts.add(_account("usr_000001", "other@example.com")) is False
    assert accounts.get("usr_000002") is None and accounts.by_email("other@example.com") is None
    assert accounts.get("camila") is None and accounts.by_email("nobody@example.com") is None


def test_sample_flag_defaults_off_and_persists(stores):
    accounts, _ = stores
    accounts.add(_account())
    assert accounts.get("usr_000001").sample_data is False
    assert accounts.set_sample_data("usr_000001", True) is True
    assert accounts.get("usr_000001").sample_data is True and accounts.by_email("ana@example.com").sample_data is True
    assert accounts.set_sample_data("usr_000001", True) is True
    assert accounts.set_sample_data("camila", True) is False and accounts.get("camila") is None


def test_session_round_trip_by_digest_only(stores):
    _, sessions = stores
    session = _session()
    sessions.add(session)
    assert sessions.by_token_hash(token_digest(TOKEN)) == session
    assert session.token_hash == token_digest(TOKEN) and TOKEN not in [getattr(session, n) for n in session.__slots__]
    assert sessions.by_token_hash(TOKEN) is None and sessions.by_token_hash(token_digest("other")) is None


def test_revoke_is_single_shot(stores):
    _, sessions = stores
    sessions.add(_session())
    later = NOW + timedelta(hours=1)
    assert sessions.revoke("sess_000001", later) is True
    assert sessions.revoke("sess_000001", later + timedelta(hours=1)) is False
    assert sessions.revoke("sess_unknown", later) is False
    assert sessions.by_token_hash(token_digest(TOKEN)).revoked_at == later


def test_concurrent_adds_of_one_email_let_exactly_one_win(stores):
    accounts, _ = stores
    barrier = threading.Barrier(8)
    results = []

    def add(i):
        barrier.wait()
        results.append(accounts.add(_account(f"usr_{i:06d}", "race@example.com")))

    threads = [threading.Thread(target=add, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [False] * 7 + [True]


def test_concurrent_revokes_let_exactly_one_win(stores):
    _, sessions = stores
    sessions.add(_session())
    barrier = threading.Barrier(8)
    results = []

    def revoke():
        barrier.wait()
        results.append(sessions.revoke("sess_000001", NOW + timedelta(minutes=5)))

    threads = [threading.Thread(target=revoke) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [False] * 7 + [True]


def test_sqlite_survives_reopen_and_never_stores_the_token(tmp_path):
    path = tmp_path / "accounts.db"
    db = SqliteDatabase(path)
    SqliteUserAccountStore(db).add(_account())
    SqliteUserAccountStore(db).set_sample_data("usr_000001", True)
    SqliteSessionStore(db).add(_session())
    SqliteSessionStore(db).add(_session("sess_000002", "second-token-never-stored"))
    SqliteSessionStore(db).revoke("sess_000002", NOW)
    db.connection.close()

    reopened = SqliteDatabase(path)
    account = SqliteUserAccountStore(reopened).get("usr_000001")
    assert account == UserAccount("usr_000001", "ana@example.com", HASH, NOW, sample_data=True)
    assert SqliteSessionStore(reopened).by_token_hash(token_digest(TOKEN)) == _session()
    assert SqliteSessionStore(reopened).by_token_hash(token_digest("second-token-never-stored")).revoked_at == NOW
    dump = "\n".join(reopened.connection.iterdump())
    assert TOKEN not in dump and "second-token-never-stored" not in dump
    assert token_digest(TOKEN) in dump
