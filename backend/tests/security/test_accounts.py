from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import Final

import pytest
from fastapi.testclient import TestClient

from neural_ledger.adapters.inbound.http.app import create_app
from neural_ledger.application.conversation import UserEntry
from neural_ledger.bootstrap.config import Settings
from neural_ledger.bootstrap.container import build
from tests.security.helpers import ScriptedFakeLLM, call, say
from tests.statement_samples import santander_pdf

pytestmark = pytest.mark.security
REPO: Final = Path(__file__).resolve().parents[3]
ORIGIN: Final = "http://localhost:5173"
EMAIL_A: Final = "alice@accounts.invalid"
EMAIL_B: Final = "bob@accounts.invalid"
PASSWORD: Final = "synthetic-password-123"
SESSION: Final = "shared"
SPOOF: Final = "forged-identity"


# --- PR3 handoff seams: auth request fields and app wiring are not contracted yet. ---
def app_for(monkeypatch, *, auth="accounts", llm=None, sqlite_path=None):
    env = {
        "NL_AUTH": auth,
        "NL_LLM": "scripted",
        "NL_CLOCK": "fixed",
        "NL_IDS": "sequential",
        "NL_DATA_DIR": str(REPO / "data"),
        "NL_CONTRACTS_DIR": str(REPO / "contracts"),
        "NL_APP_ORIGINS": ORIGIN,
        "NL_HMAC_SECRET": "synthetic-test-secret-at-least-16-chars",
    }
    if sqlite_path is not None:
        env.update(NL_PERSISTENCE="sqlite", NL_SQLITE_PATH=str(sqlite_path))
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    if llm is not None:
        monkeypatch.setattr("neural_ledger.bootstrap.container.ScriptedLanguageModel", lambda: llm)
    settings = Settings.from_env(env)
    services, adapters = build(settings)
    client = TestClient(create_app(services, cors_origins=settings.cors_origins), headers={"Origin": ORIGIN})
    return client, services, adapters


def signup(client, email=EMAIL_A, password=PASSWORD):
    response = client.post("/v1/auth/signup", json={"email": email, "password": password, "display_name": "Synthetic User", "sandbox_acknowledged": True})
    assert response.status_code in (200, 201), "signup must create a synthetic account"
    assert client.cookies.get("nl_session"), "signup must issue a session"
    return response


def signin(client, email=EMAIL_A, password=PASSWORD):
    response = client.post("/v1/auth/signin", json={"email": email, "password": password})
    assert response.status_code in (200, 201), "valid credentials must sign in"
    assert client.cookies.get("nl_session"), "signin must issue a session"
    return response


def demo_session(client, persona="camila"):
    response = client.post("/v1/auth/demo-session", json={"persona": persona})
    assert response.status_code in (200, 201), "allowlisted persona must get a session"
    assert client.cookies.get("nl_session"), "demo-session must issue a session"
    return response


def audit_events(client, session_id=SESSION):
    response = client.get("/v1/audit", params={"session_id": session_id})
    assert response.status_code == 200, "own audit must be readable"
    return response.json()["events"]


def own_user_id(client):
    events = audit_events(client)
    assert events, "own chat must create audit events"
    identities = {event["user_id"] for event in events}
    assert len(identities) == 1
    return identities.pop()


def chat(client, message="Will I be OK in December?"):
    response = client.post("/v1/chat", json={"session_id": SESSION, "message": message})
    assert response.status_code == 200, "own chat must work"
    return response


def profile(client):
    response = client.get("/v1/profile")
    assert response.status_code == 200, "own profile must be readable"
    return response.json()["data"]


def read_code(response, expected):
    assert response.status_code in (400, 403), "expected a client rejection"
    assert expected in response.text, "expected the specified machine error code"


@pytest.fixture
def accounts(monkeypatch):
    return app_for(monkeypatch)


@pytest.mark.parametrize("path,method,payload", [
    ("/v1/auth/signin", "post", {"email": EMAIL_A, "password": PASSWORD}),
    ("/v1/audit/verify", "get", None),
    ("/v1/state", "get", None),
])
def test_s16_header_rejected_without_session(accounts, path, method, payload):
    client, _, _ = accounts
    response = client.request(method, path, json=payload, headers={"X-User-Id": SPOOF})
    assert response.status_code == 400
    assert "IDENTITY_HEADER_REJECTED" in response.text


def test_s16_header_rejected_with_valid_session(accounts):
    client, _, _ = accounts
    signup(client)
    response = client.get("/v1/state", headers={"X-User-Id": SPOOF})
    assert response.status_code == 400
    assert "IDENTITY_HEADER_REJECTED" in response.text
    assert all(event["user_id"] != SPOOF for event in audit_events(client))


def test_s16_health_is_only_header_exception(accounts):
    client, _, _ = accounts
    response = client.get("/health", headers={"X-User-Id": SPOOF})
    assert response.status_code == 200
    assert response.json().get("auth") == "accounts"


@pytest.mark.parametrize("method,path,body", [
    ("get", "/v1/state", None),
    ("get", "/v1/commitments", None),
    ("post", "/v1/chat", {"session_id": SESSION, "message": "Hello"}),
    ("get", "/v1/audit", None),
    ("get", "/v1/statements", None),
    ("post", "/v1/documents", None),
    ("get", "/v1/receipts", None),
    ("get", "/v1/spending", None),
    ("get", "/v1/me", None),
    ("get", "/v1/profile", None),
    ("get", "/v1/profile/questionnaire", None),
])
def test_s16_protected_routes_require_session(accounts, method, path, body):
    client, _, _ = accounts
    assert client.request(method, path, json=body).status_code == 401


def test_s16_public_routes_do_not_require_session(accounts):
    client, _, _ = accounts
    assert client.get("/health").status_code == 200
    assert client.get("/v1/audit/verify").status_code == 200
    signup(client)
    client.cookies.clear()
    signin(client)
    client.cookies.clear()
    demo_session(client)


def test_s16_forged_cookie_is_unauthorized(accounts):
    client, _, _ = accounts
    client.cookies.set("nl_session", "not-a-valid-session")
    assert client.get("/v1/me").status_code == 401


def test_s16_demo_mode_preserves_header_only_for_reads(monkeypatch):
    client, _, _ = app_for(monkeypatch, auth="demo")
    assert client.get("/v1/state", headers={"X-User-Id": "diego"}).status_code == 200
    assert client.get("/health").json().get("auth") == "demo"
    response = client.post("/v1/auth/signin", json={"email": EMAIL_A, "password": PASSWORD})
    assert response.status_code == 404
    read_code(client.put("/v1/profile", json={"display_name": "New Name"}), "PROFILE_READ_ONLY")


def test_s17_absolute_expiry_does_not_slide(accounts):
    client, services, _ = accounts
    signup(client)
    assert client.get("/v1/me").status_code == 200
    services.clock.advance(hours=11)
    assert client.get("/v1/me").status_code == 200
    services.clock.advance(minutes=59)
    assert client.get("/v1/me").status_code == 200
    services.clock.advance(minutes=2)
    assert client.get("/v1/me").status_code == 401


def test_s17_signout_revokes_captured_token(accounts):
    client, _, _ = accounts
    signup(client)
    token = client.cookies.get("nl_session")
    assert token
    assert client.get("/v1/me").status_code == 200
    assert client.post("/v1/auth/signout", json={}).status_code in (200, 204)
    client.cookies.set("nl_session", token)
    assert client.get("/v1/me").status_code == 401


def test_s17_cookie_flags_and_audit_privacy(accounts):
    client, _, _ = accounts
    response = signup(client)
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/" in cookie
    chat(client)
    audit = client.get("/v1/audit", params={"session_id": SESSION})
    assert audit.status_code == 200 and audit.json()["events"]
    email_omitted = EMAIL_A not in audit.text
    token_omitted = client.cookies["nl_session"] not in audit.text
    assert email_omitted, "audit must omit account email"
    assert token_omitted, "audit must omit session token"


def test_s17_sqlite_stores_token_hash_not_token(monkeypatch, tmp_path):
    database = tmp_path / "accounts.db"
    client, _, _ = app_for(monkeypatch, sqlite_path=database)
    signup(client)
    token = client.cookies["nl_session"]
    assert client.get("/v1/me").status_code == 200
    with sqlite3.connect(database) as connection:
        tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        stored = b" ".join(
            str(value).encode() if not isinstance(value, bytes) else value
            for table in tables
            for row in connection.execute(f'SELECT * FROM "{table}"')
            for value in row
        )
    persisted = stored + database.read_bytes()
    wal = database.with_name(database.name + "-wal")
    if wal.exists():
        persisted += wal.read_bytes()
    digest = hashlib.sha256(token.encode()).digest()
    hash_stored = digest in persisted or digest.hex().encode() in persisted
    token_omitted = token.encode() not in persisted
    password_omitted = PASSWORD.encode() not in persisted
    assert hash_stored, "token hash must be persisted"
    assert token_omitted, "plaintext session token must not be persisted"
    assert password_omitted, "plaintext password must not be persisted"


def test_s18_distinct_accounts_and_persona_audit_scope(monkeypatch):
    client, _, _ = app_for(monkeypatch)
    signup(client)
    chat(client)
    first = own_user_id(client)
    client.cookies.clear()
    signup(client, EMAIL_B)
    chat(client)
    second = own_user_id(client)
    client.cookies.clear()
    demo_session(client)
    chat(client)
    persona = own_user_id(client)
    assert first.startswith("usr_") and second.startswith("usr_")
    assert len({first, second, persona}) == 3 and persona == "camila"
    assert audit_events(client) and {event["user_id"] for event in audit_events(client)} == {persona}


def test_s18_profile_and_state_do_not_cross_accounts(monkeypatch):
    client, _, _ = app_for(monkeypatch)
    signup(client)
    updated = client.put("/v1/profile", json={"display_name": "Alice Only", "language": "en"})
    assert updated.status_code == 200
    first_profile = profile(client)
    assert first_profile["display_name"] == {"untrusted_text": "Alice Only"}
    client.cookies.clear()
    signup(client, EMAIL_B)
    other = profile(client)
    assert other["user_id"] != first_profile["user_id"]
    assert "Alice Only" not in str(other) and "Camila" not in str(other)
    other_state = client.get("/v1/state")
    assert other_state.status_code in (200, 409)
    assert "Camila" not in other_state.text
    assert "ignore previous instructions" not in client.get("/v1/commitments").text
    client.cookies.clear()
    demo_session(client)
    assert profile(client)["display_name"] == {"untrusted_text": "Camila"}
    assert client.get("/v1/state").status_code == 200
    assert "ignore previous instructions" in client.get("/v1/commitments").text


def test_s18_statement_list_and_detail_are_owner_scoped(monkeypatch):
    client, _, _ = app_for(monkeypatch)
    signup(client)
    upload = client.post("/v1/statements", content=santander_pdf(), headers={"Content-Type": "application/pdf"})
    assert upload.status_code == 200, "owner must be able to upload synthetic statement"
    statement_id = upload.json()["data"]["imports"][0]["statement"]["statement_id"]
    own_list = client.get("/v1/statements")
    assert own_list.status_code == 200
    assert statement_id in {item["statement_id"] for item in own_list.json()["data"]}
    client.cookies.clear()
    signup(client, EMAIL_B)
    other_list = client.get("/v1/statements")
    assert other_list.status_code == 200 and other_list.json()["data"] == []
    other_detail = client.get(f"/v1/statements/{statement_id}")
    assert other_detail.status_code != 200
    assert "Compra Nacional MD SHOP ONE" not in other_detail.text


def test_s18_conversation_is_user_scoped_even_with_same_session_id(monkeypatch):
    llm = ScriptedFakeLLM([say("ok")] * 5)
    client, _, _ = app_for(monkeypatch, llm=llm)
    demo_session(client)
    chat(client, "Camila first turn")
    chat(client, "Camila second turn")
    assert len(llm.requests[-1].entries) == 3
    client.cookies.clear()
    signup(client, EMAIL_A)
    chat(client, "Alice first turn")
    assert len(llm.requests[-1].entries) == 1
    assert isinstance(llm.requests[-1].entries[0], UserEntry)
    client.cookies.clear()
    signup(client, EMAIL_B)
    chat(client, "Bob first turn")
    assert len(llm.requests[-1].entries) == 1
    chat(client, "Bob second turn")
    assert len(llm.requests[-1].entries) == 3


@pytest.mark.parametrize("persona", ["usr_1", "eve"])
def test_s18_demo_session_rejects_unlisted_personas(accounts, persona):
    client, _, _ = accounts
    demo_session(client)
    client.cookies.clear()
    response = client.post("/v1/auth/demo-session", json={"persona": persona})
    assert 400 <= response.status_code < 500
    assert not client.cookies.get("nl_session")


@pytest.mark.parametrize("auth", ["accounts", "demo"])
@pytest.mark.parametrize("name", [
    "update_user_profile", "set_risk_tolerance", "submit_questionnaire", "update_profile",
])
def test_s19_hostile_model_cannot_write_profile(monkeypatch, auth, name):
    llm = ScriptedFakeLLM([call(name, display_name="Escalated", tolerance="aggressive"), say("ok")])
    client, _, _ = app_for(monkeypatch, auth=auth, llm=llm)
    if auth == "accounts":
        signup(client)
    before = profile(client)
    reply = chat(client)
    blocked = [event for event in audit_events(client) if event["tool_requested"] == name]
    assert blocked and blocked[-1]["kind"] == "ACTION_BLOCKED"
    assert blocked[-1]["permission_tier"] == "T3"
    assert blocked[-1]["blocked_reason"] == "SELF_ESCALATION"
    assert blocked[-1]["actor"] == "agent"
    assert reply.json()["blocked_reason"] == "SELF_ESCALATION"
    assert llm.requests and name not in {tool.name for tool in llm.requests[0].tools}
    assert all(event["kind"] != "PROFILE_UPDATED" for event in audit_events(client))
    assert profile(client) == before


def test_s20_absent_email_matches_wrong_password_and_hashes_both(monkeypatch):
    client, _, _ = app_for(monkeypatch)
    signup(client)
    client.cookies.clear()
    real_scrypt = hashlib.scrypt
    calls = []

    def counted_scrypt(*args, **kwargs):
        calls.append(1)
        return real_scrypt(*args, **kwargs)

    monkeypatch.setattr(hashlib, "scrypt", counted_scrypt)
    wrong = client.post("/v1/auth/signin", json={"email": EMAIL_A, "password": "wrong-password-123"})
    wrong_count = len(calls)
    absent = client.post("/v1/auth/signin", json={"email": "absent@accounts.invalid", "password": "wrong-password-123"})
    absent_count = len(calls) - wrong_count
    assert 400 <= wrong.status_code < 500 and wrong.status_code != 404
    responses_match = wrong.status_code == absent.status_code and wrong.content == absent.content
    assert responses_match, "signin failure responses must match byte-for-byte"
    assert not client.cookies.get("nl_session")
    assert "nl_session" not in wrong.headers.get("set-cookie", "")
    assert "nl_session" not in absent.headers.get("set-cookie", "")
    assert wrong_count >= 1 and absent_count >= 1, "both failures must invoke password hashing"
    signin(client)
