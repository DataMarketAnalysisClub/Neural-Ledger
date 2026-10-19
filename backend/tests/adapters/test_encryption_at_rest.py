"""Option B, change 3: nothing personal is left in clear in the SQLite file.

Profiles (questionnaire answers), accounts (email, password hash), proposals, authorizations, savings rules and
audit records are sealed like statements and transactions; the email is found by an HMAC blind index. The tests
read the raw bytes of the database and its WAL and look for values they know were written."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("cryptography")

from neural_ledger.adapters.inbound.http.app import create_app  # noqa: E402
from neural_ledger.adapters.outbound.persistence.field_cipher import FieldCipher, FieldCipherError  # noqa: E402
from neural_ledger.adapters.outbound.persistence.sqlite import SCHEMA_VERSION, SqliteDatabase, email_index  # noqa: E402
from neural_ledger.adapters.outbound.persistence.sqlite_migration import migrate  # noqa: E402
from neural_ledger.adapters.outbound.system.password import ScryptHasher  # noqa: E402
from neural_ledger.application.use_cases.actions import ActorContext  # noqa: E402
from neural_ledger.bootstrap.container import build  # noqa: E402
from neural_ledger.domain.audit.events import Actor, AuditDraft, AuditKind, seal  # noqa: E402
from neural_ledger.domain.shared.serialization import to_primitive  # noqa: E402
from neural_ledger.domain.user.account import UserAccount  # noqa: E402
from neural_ledger.domain.user.profile import UserProfile  # noqa: E402
from neural_ledger.domain.user.questionnaire import CURRENT_VERSION, REGISTRY  # noqa: E402
from tests.conftest import make_settings  # noqa: E402
from tests.statement_samples import santander_xlsx  # noqa: E402

ORIGIN = "http://localhost:3000"
KEY = "5e" * 32
EMAIL = "zelda.quintana@accounts.invalid"
NAME = "Zelda Quintana"
PASSWORD = "synthetic-password-zq"


def _raw(path: Path) -> bytes:
    """The database and its write-ahead log, as an attacker who copied the volume would read them."""
    wal = path.with_name(path.name + "-wal")
    return path.read_bytes() + (wal.read_bytes() if wal.exists() else b"")


def _settings(path: Path, **overrides):
    return make_settings(persistence="sqlite", sqlite_path=str(path), data_key=KEY, auth="accounts", app_origins=(ORIGIN,), **overrides)


def _client(path: Path):
    services, adapters = build(_settings(path))
    return TestClient(create_app(services, cors_origins=(ORIGIN,)), headers={"Origin": ORIGIN}), services, adapters


def _write_everything(path: Path) -> tuple:
    """An account with questionnaire answers, and a persona that proposes, confirms and executes a savings rule."""
    client, services, adapters = _client(path)
    signup = {"email": EMAIL, "password": PASSWORD, "display_name": NAME, "sandbox_acknowledged": True}
    assert client.post("/v1/auth/signup", json=signup).status_code == 201
    answers = [{"question_id": q.question_id, "option_id": q.options[1].option_id} for q in REGISTRY[CURRENT_VERSION].questions]
    assert client.post("/v1/profile/questionnaire", json={"version": CURRENT_VERSION, "answers": answers}).json()["status"] == "OK"
    assert client.post("/v1/statements", content=santander_xlsx()).json()["status"] == "OK"
    client.post("/v1/auth/signout")
    assert client.post("/v1/auth/demo-session", json={"persona": "camila"}).status_code == 200
    plan = client.post("/v1/savings-plan", json={}).json()
    proposal = client.post("/v1/actions/proposals", json={"session_id": "z", "plan_snapshot_id": plan["snapshot_id"]}).json()["proposal"]
    confirmed = client.post(f"/v1/actions/proposals/{proposal['proposal_id']}/confirm", json={"session_id": "z", "terms": proposal["terms"]})
    executed = client.post("/v1/actions/execute", json={"session_id": "z", "authorization_id": confirmed.json()["authorization"]["authorization_id"]})
    assert executed.json()["status"] == "EXECUTED"
    return client, services, adapters, answers


def test_no_personal_value_is_in_clear_in_the_database_file(tmp_path):
    path = tmp_path / "nl.db"
    _, services, adapters, answers = _write_everything(path)
    raw = _raw(path)
    known = [
        EMAIL, NAME, "Zelda", "scrypt$",  # the account and its profile
        *{a["option_id"] for a in answers}, "declared_tolerance", "questionnaire_version",  # the questionnaire
        "sandbox_savings", "source_account", "action_hash", "set_liquidity_floor", "create_savings_rule",  # proposals, rules
        "USER_REGISTERED", "PROFILE_UPDATED", "ACTION_EXECUTED", "sandbox_notice=", "fields=questionnaire",  # audit
        "SHOP ONE", "Compra Nacional",  # the statement and its transactions
    ]
    leaks = [value for value in known if value.encode() in raw]
    assert leaks == []
    assert b"nlenc2:" in raw and b"nlenc1:" not in raw
    assert services.audit.verify().ok and adapters.audit_log.events()  # the chain still verifies, over the plaintext records


def test_the_email_is_found_by_its_blind_index_only(tmp_path):
    path = tmp_path / "nl.db"
    client, services, _, _ = _write_everything(path)
    db = SqliteDatabase(path)
    (index,) = db.connection.execute("SELECT email_index FROM user_accounts").fetchone()
    cipher = FieldCipher.from_hex(KEY)
    assert index == email_index(cipher, EMAIL) and len(index) == 64
    assert index != hashlib.sha256(EMAIL.encode()).hexdigest()  # keyed: no dictionary of addresses finds it
    assert "email" not in {name for (name,) in db.connection.execute("SELECT name FROM pragma_table_info('user_accounts')")}
    assert client.post("/v1/auth/signin", json={"email": EMAIL.upper(), "password": PASSWORD}).status_code == 200
    assert client.post("/v1/auth/signup", json={"email": EMAIL, "password": PASSWORD, "display_name": "Other", "sandbox_acknowledged": True}).status_code == 409


def test_sealed_rows_are_bound_to_their_owner(tmp_path):
    path = tmp_path / "nl.db"
    _write_everything(path)
    db = SqliteDatabase(path)
    db.connection.execute("UPDATE proposals SET user_id = 'diego'")  # move camila's proposal to another user
    services, _ = build(_settings(path))
    with pytest.raises(FieldCipherError):
        services.actions.pending(ActorContext(session_id="z", user_id="diego", actor=Actor.USER))


# ---- a database from before (schema 0) --------------------------------------------------------------

V0_SCHEMA = """
CREATE TABLE proposals (proposal_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE authorizations (authorization_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, payload TEXT NOT NULL, consumed_at TEXT);
CREATE TABLE audit_events (sequence INTEGER PRIMARY KEY, event_id TEXT NOT NULL UNIQUE, session_id TEXT NOT NULL,
    prev_hash TEXT NOT NULL, event_hash TEXT NOT NULL, record TEXT NOT NULL);
CREATE TABLE statements (sequence INTEGER PRIMARY KEY, statement_id TEXT NOT NULL, user_id TEXT NOT NULL, payload TEXT NOT NULL,
    UNIQUE (user_id, statement_id));
CREATE TABLE transactions (sequence INTEGER PRIMARY KEY, txn_id TEXT NOT NULL, user_id TEXT NOT NULL, posted_on TEXT NOT NULL,
    payload TEXT NOT NULL, UNIQUE (user_id, txn_id));
CREATE TABLE savings_rules (sequence INTEGER PRIMARY KEY, rule_id TEXT NOT NULL UNIQUE, user_id TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE user_profiles (user_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE user_accounts (user_id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, payload TEXT NOT NULL, sample_data INTEGER NOT NULL DEFAULT 0);
CREATE TABLE sessions (session_ref TEXT PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE, user_id TEXT NOT NULL, payload TEXT NOT NULL,
    revoked_at TEXT);
"""
NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)


def _v0_database(path: Path) -> str:
    """The layout and the plain rows the code before option B wrote: the email in clear as the lookup column."""
    import sqlite3

    conn = sqlite3.connect(path, isolation_level=None)
    conn.executescript(V0_SCHEMA)
    user_id = "usr_legacy"
    account = to_primitive(UserAccount(user_id, EMAIL, ScryptHasher().hash(PASSWORD), NOW))
    account.pop("sample_data")
    conn.execute("INSERT INTO user_accounts VALUES (?, ?, ?, 0)", (user_id, EMAIL, json.dumps(account)))
    conn.execute("INSERT INTO user_profiles VALUES (?, ?)", (user_id, json.dumps(to_primitive(UserProfile(user_id, NAME)))))
    prev = "0" * 64
    for sequence, kind in enumerate((AuditKind.USER_REGISTERED, AuditKind.SESSION_STARTED), start=1):
        draft = AuditDraft(f"evt_{sequence}", NOW, "sess_legacy", Actor.USER, kind, detail="reason=signup", user_id=user_id)
        event = seal(draft, sequence, prev)
        conn.execute(
            "INSERT INTO audit_events VALUES (?, ?, ?, ?, ?, ?)",
            (sequence, draft.event_id, draft.session_id, prev, event.event_hash, json.dumps(event.to_record())),
        )
        prev = event.event_hash
    conn.close()
    return user_id


def test_a_schema_0_database_is_upgraded_and_sealed_at_startup(tmp_path):
    path = tmp_path / "legacy.db"
    user_id = _v0_database(path)
    assert EMAIL.encode() in _raw(path)
    services, adapters = build(_settings(path))
    assert services.accounts.signin(EMAIL, PASSWORD).ok  # found through the new blind index
    assert services.profiles.user_profile(user_id).data.display_name == {"untrusted_text": NAME}
    events = adapters.audit_log.events()
    assert [e.sequence for e in events][:2] == [1, 2] and services.audit.verify().ok  # same chain, same hashes
    assert SqliteDatabase(path).connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert EMAIL.encode() not in _raw(path) and NAME.encode() not in _raw(path)  # VACUUM left no old page behind


def test_a_dry_run_on_a_schema_0_database_writes_nothing(tmp_path):
    path = tmp_path / "legacy.db"
    _v0_database(path)
    before = _dump(path)
    db = SqliteDatabase(path)
    assert db.needs_migration
    report = migrate(db, FieldCipher.from_hex(KEY), dry_run=True)
    assert report.schema_from == 0 and report.columns["user_accounts"].sealed == 1 and report.columns["audit_events"].sealed == 2
    assert db.connection.execute("PRAGMA user_version").fetchone()[0] == 0
    db.connection.close()
    assert _dump(path) == before  # schema and rows (opening the file only switches it to WAL mode)


def _dump(path: Path) -> list[str]:
    import sqlite3

    conn = sqlite3.connect(path)
    try:
        return list(conn.iterdump()) + [str(conn.execute("PRAGMA user_version").fetchone()[0])]
    finally:
        conn.close()
