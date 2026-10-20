"""G03 (Ley 21.719 art. 7): a user deletes their account and everything it owns; a demo persona is reset instead.

Deleting user A leaves user B intact, ends every session of A, and leaves no row that refers to A in any table
(SQLite is scanned table by table, column by column, raw bytes included). The audit chain is one log for every
user: A's events become tombstones and the chain still verifies; a forged tombstone does not."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from neural_ledger.adapters.inbound.http.app import create_app
from neural_ledger.adapters.outbound.bank.simulated import SimulatedSandboxBank
from neural_ledger.adapters.outbound.persistence.memory import InMemorySavingsRuleStore
from neural_ledger.adapters.outbound.persistence.sqlite import SqliteDatabase, SqliteSavingsRuleStore
from neural_ledger.bootstrap.container import build
from neural_ledger.domain.actions.terms import ActionTerms, ActionType, Frequency, Proposal, ProposalStatus
from neural_ledger.domain.audit.events import Actor, AuditDraft, AuditKind, erasure_detail, seal, tombstone, verify_chain
from neural_ledger.domain.memory.catalog import ChatOrigin, Declaration, SalaryNet, Source
from neural_ledger.domain.memory.proposals import ReadAs
from neural_ledger.domain.shared.month import Month
from tests.conftest import TEST_CIPHER, make_settings
from tests.receipt_samples import boleta_pdf
from tests.statement_samples import santander_xlsx

pytestmark = pytest.mark.security

ORIGIN = "http://localhost:3000"
KEY = "7a" * 32
EMAIL_A, EMAIL_B = "alice.deleted@accounts.invalid", "bruno.kept@accounts.invalid"
NAME_A, NAME_B = "Alicia Borrada", "Bruno Queda"
PASSWORD = "synthetic-password-del"


def _world(tmp_path: Path, persistence: str):
    extra = {"persistence": "sqlite", "sqlite_path": str(tmp_path / "del.db"), "data_key": KEY} if persistence == "sqlite" else {}
    services, adapters = build(make_settings(auth="accounts", app_origins=(ORIGIN,), **extra))
    app = create_app(services, cors_origins=(ORIGIN,))
    return services, adapters, (lambda: TestClient(app, headers={"Origin": ORIGIN}))


def _signup(new_client, email: str, name: str):
    client = new_client()
    response = client.post("/v1/auth/signup", json={"email": email, "password": PASSWORD, "display_name": name, "sandbox_acknowledged": True})
    assert response.status_code == 201, response.text
    assert client.post("/v1/statements", content=santander_xlsx()).json()["status"] == "OK"
    assert client.post("/v1/documents", content=boleta_pdf()).json()["status"] == "OK"  # a receipt too (ADR-039)
    return client, response.json()["user_id"]


def _give_actions(adapters, user_id: str) -> None:
    """A proposal, a rule and a declared salary, written straight to the stores (a new account has no plan to propose)."""
    terms = ActionTerms(ActionType.CREATE_SAVINGS_RULE, 50_000, "CLP", Frequency.MONTHLY, "checking", "sandbox_savings", date(2026, 11, 1))
    now = adapters.clock.now()
    adapters.actions_repo.add_proposal(Proposal(f"prop_{user_id}", "s1", user_id, terms, "snap", now, now + timedelta(minutes=10), ProposalStatus.PENDING))
    adapters.bank.create_savings_rule(user_id, terms, f"auth_{user_id}", f"exec_{user_id}")
    salary = Declaration(
        f"mem_{user_id}", f"chn_{user_id}", 1, user_id, SalaryNet(1_200_000, Month.parse("2026-11")), now, Source.CHAT,
        ChatOrigin(f"s_{user_id}", f"msg_{user_id}"), f"evt_mem_{user_id}",
    )
    assert adapters.memory_store.append((salary,), 0)


@pytest.fixture(params=["memory", "sqlite"])
def two_accounts(request, tmp_path):
    services, adapters, new_client = _world(tmp_path, request.param)
    a, user_a = _signup(new_client, EMAIL_A, NAME_A)
    b, user_b = _signup(new_client, EMAIL_B, NAME_B)
    _give_actions(adapters, user_a)
    _give_actions(adapters, user_b)
    for user in (user_a, user_b):  # the memory consent and a pending proposal, through the real writes (ADR-048)
        assert services.memory.set_consent(user, "s1", {"consent": "granted"}).ok
        assert services.memory.prepare(user, ChatOrigin("s1", f"msg_p_{user}"), (1_300_000,), Month.parse("2026-12"), ReadAs.NEXT_OCCURRENCE).ok
    return request.param, tmp_path, services, adapters, new_client, (a, user_a), (b, user_b)


def test_a_wrong_password_or_confirmation_deletes_nothing(two_accounts):
    _, _, services, adapters, _, (a, user_a), _ = two_accounts
    before = adapters.audit_log.events()
    wrong = a.request("DELETE", "/v1/account", json={"confirm": "DELETE", "password": "not-the-password"})
    assert wrong.status_code == 401 and wrong.json()["status"] == "INVALID_CREDENTIALS"
    unconfirmed = a.request("DELETE", "/v1/account", json={"confirm": "delete me", "password": PASSWORD})
    assert unconfirmed.status_code == 422 and unconfirmed.json()["field"] == "confirm"
    missing = a.request("DELETE", "/v1/account", json={"password": PASSWORD})
    assert missing.status_code == 422 and missing.json()["field"] == "confirm"
    for response in (wrong, unconfirmed, missing):
        assert PASSWORD not in response.text and "set-cookie" not in response.headers
    assert adapters.audit_log.events() == before and a.get("/v1/me").json()["user_id"] == user_a


@pytest.mark.parametrize("confirm", ["DELETE", EMAIL_A, f"  {EMAIL_A.upper()} "])
def test_deleting_a_leaves_b_intact_and_ends_every_session_of_a(two_accounts, confirm):
    _, _, services, adapters, new_client, (a, user_a), (b, user_b) = two_accounts
    second = new_client()
    assert second.post("/v1/auth/signin", json={"email": EMAIL_A, "password": PASSWORD}).status_code == 200
    b_statements = b.get("/v1/statements").json()["data"]
    b_transactions = b.get("/v1/transactions").json()["data"]

    response = a.request("DELETE", "/v1/account", json={"confirm": confirm, "password": PASSWORD})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "DELETED" and body["erased"]["user_accounts"] == 1 and body["erased"]["sessions"] == 2
    assert body["erased"]["statements"] >= 1 and body["erased"]["savings_rules"] == 1 and body["audit_events_erased"] >= 4
    assert body["erased"]["receipts"] == 1 and body["erased"]["user_memory"] == 1
    assert body["erased"]["memory_state"] == 1 and body["erased"]["memory_proposals"] == 1
    assert not adapters.memory_writes.state(user_a).granted and adapters.memory_writes.state(user_b).granted
    assert adapters.memory_store.for_user(user_a) == () and len(adapters.memory_store.for_user(user_b)) == 1
    assert "Max-Age=0" in response.headers["set-cookie"]
    assert second.get("/v1/me").status_code == 401  # the other session of A ends too
    a.cookies.clear()
    assert a.post("/v1/auth/signin", json={"email": EMAIL_A, "password": PASSWORD}).status_code == 401
    # B is untouched
    assert b.get("/v1/me").json()["user_id"] == user_b
    assert b.get("/v1/statements").json()["data"] == b_statements and b.get("/v1/transactions").json()["data"] == b_transactions
    assert b.get("/v1/profile").json()["data"]["display_name"] == {"untrusted_text": NAME_B}
    assert [r.rule_id for r in adapters.bank.active_rules(user_b)] and not adapters.bank.active_rules(user_a)
    assert new_client().post("/v1/auth/signin", json={"email": EMAIL_B, "password": PASSWORD}).status_code == 200
    # the chain still verifies; B still reads their own events
    assert services.audit.verify().ok and b.get("/v1/audit").json()["chain_ok"]
    assert b.get("/v1/audit").json()["events"]
    # the email can be registered again: nothing of A is left to collide with
    assert _signup(new_client, EMAIL_A, NAME_A)[1] != user_a


def test_no_row_in_any_table_refers_to_the_deleted_user(two_accounts):
    persistence, tmp_path, services, adapters, _, (a, user_a), (b, user_b) = two_accounts
    # A's own sign-in sessions; imports log under the shared session id "statements", which is not A's
    session_refs = {e.draft.session_id for e in adapters.audit_log.events() if e.draft.user_id == user_a and e.draft.session_id.startswith("sess_")}
    assert session_refs
    assert a.request("DELETE", "/v1/account", json={"confirm": "DELETE", "password": PASSWORD}).status_code == 200
    events = adapters.audit_log.events()
    assert not [e for e in events if e.draft.user_id == user_a or e.draft.session_id in session_refs]
    erasure = [e for e in events if e.draft.kind is AuditKind.ACCOUNT_DELETED]
    assert len(erasure) == 1 and erasure[0].draft.user_id is None and user_a not in (erasure[0].draft.detail or "")
    assert {e.draft.kind for e in events if e.draft.detail and erasure[0].draft.event_id in e.draft.detail} == {AuditKind.ERASED}
    if persistence != "sqlite":
        return
    db = SqliteDatabase(tmp_path / "del.db")
    needles = (user_a, EMAIL_A, NAME_A, *session_refs)
    tables = [name for (name,) in db.connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
    found = []
    for table in tables:
        for row in db.connection.execute(f'SELECT * FROM "{table}"'):  # noqa: S608 - names from sqlite_master, test only
            for value in row:
                found += [(table, needle) for needle in needles if needle in str(value)]
    assert found == []
    # Sealed values: open every one and look inside too.
    from neural_ledger.adapters.outbound.persistence.field_cipher import FieldCipher
    from neural_ledger.adapters.outbound.persistence.sqlite import SEALED_COLUMNS

    cipher = FieldCipher.from_hex(KEY)
    inside = [
        (column.table, needle)
        for column in SEALED_COLUMNS
        for record in db.connection.execute(column.select)
        for needle in needles
        if needle in cipher.open(record[-1], column.aad(record))
    ]
    assert inside == []
    db.connection.close()
    raw = (tmp_path / "del.db").read_bytes() + ((tmp_path / "del.db-wal").read_bytes() if (tmp_path / "del.db-wal").exists() else b"")
    assert user_a.encode() not in raw
    assert user_b.encode() in raw  # B's rows are still there, by id


def test_a_demo_persona_is_reset_not_deleted(two_accounts):
    _, _, services, adapters, new_client, _, (b, user_b) = two_accounts
    visitor, other = new_client(), new_client()
    for client in (visitor, other):
        assert client.post("/v1/auth/demo-session", json={"persona": "camila"}).status_code == 200
    assert visitor.post("/v1/statements", content=santander_xlsx()).json()["status"] == "OK"
    _give_actions(adapters, "camila")
    assert visitor.get("/v1/statements").json()["data"]

    refused = visitor.request("DELETE", "/v1/account", json={"confirm": "DELETE", "password": "anything-at-all"})
    assert refused.status_code == 422 and refused.json()["field"] == "confirm"
    response = visitor.request("DELETE", "/v1/account", json={"confirm": "RESET"})

    assert response.status_code == 200 and response.json()["status"] == "RESET"
    assert "set-cookie" not in response.headers and "user_accounts" not in response.json()["erased"]
    assert visitor.get("/v1/statements").json()["data"] == [] and not adapters.bank.active_rules("camila")
    assert visitor.get("/v1/profile").json()["data"]["display_name"] == {"untrusted_text": "Camila"}  # the fixture stays
    assert visitor.get("/v1/state").status_code == 200 and other.get("/v1/me").json()["user_id"] == "camila"  # sessions stay
    assert visitor.get("/v1/audit").json()["events"] == []
    assert services.audit.verify().ok
    assert response.json()["erased"]["user_memory"] == 1 and adapters.memory_store.for_user("camila") == ()
    assert b.get("/v1/statements").json()["data"] and adapters.bank.active_rules(user_b)  # accounts untouched
    assert len(adapters.memory_store.for_user(user_b)) == 1


def test_demo_mode_has_no_account_deletion(tmp_path):
    services, _ = build(make_settings())
    response = TestClient(create_app(services)).request("DELETE", "/v1/account", json={"confirm": "RESET"}, headers={"X-User-Id": "camila"})
    assert response.status_code == 404


def test_account_deletion_is_rate_limited(two_accounts):
    _, _, _, _, _, (a, _), _ = two_accounts
    codes = [a.request("DELETE", "/v1/account", json={"confirm": "DELETE", "password": f"guess-{i:04d}-x"}).status_code for i in range(8)]
    assert codes[:5] == [401] * 5 and set(codes[5:]) == {429}


def test_no_agent_tool_reaches_account_deletion():
    catalog = (Path(__file__).parents[2] / "src/neural_ledger/application/catalog.py").read_text(encoding="utf-8")
    assert "delete_account" not in catalog and "AccountUseCases" not in catalog
    tools = Path(__file__).parents[3] / "contracts/tools"
    assert not [f.name for f in tools.glob("*.json") if "delet" in f.name or "erase" in f.name]


# ---- rule ids stay unique after another user's rules are deleted --------------------------------------


@pytest.mark.parametrize("store", ["memory", "sqlite"])
def test_rule_ids_do_not_collide_after_a_deletion(store, tmp_path):
    rules = InMemorySavingsRuleStore() if store == "memory" else SqliteSavingsRuleStore(SqliteDatabase(tmp_path / "r.db"), TEST_CIPHER)
    bank = SimulatedSandboxBank(rules)
    terms = ActionTerms(ActionType.CREATE_SAVINGS_RULE, 10_000, "CLP", Frequency.MONTHLY, "checking", "sandbox_savings", date(2026, 11, 1))
    assert bank.create_savings_rule("a", terms, "auth_a", "x1").reference == "rule_0001"
    assert bank.create_savings_rule("b", terms, "auth_b", "x2").reference == "rule_0002"
    if store == "memory":
        rules._rules = [r for r in rules._rules if r.user_id != "a"]
    else:
        rules._db.connection.execute("DELETE FROM savings_rules WHERE user_id = 'a'")
    assert bank.create_savings_rule("b", terms, "auth_c", "x3").reference == "rule_0003"


# ---- the chain with tombstones (domain) -------------------------------------------------------------


def _chain(*owners: str | None):
    from datetime import UTC, datetime

    now = datetime(2026, 10, 1, tzinfo=UTC)
    events, prev = [], "0" * 64
    for n, owner in enumerate(owners, start=1):
        event = seal(AuditDraft(f"evt_{n}", now, f"s_{owner}", Actor.USER, AuditKind.SESSION_STARTED, user_id=owner), n, prev)
        events.append(event)
        prev = event.event_hash
    return events, now


def _erase(events, owner: str, extra_victims: tuple[int, ...] = (), commit_to: tuple[int, ...] | None = None):
    _, now = _chain()
    victims = [e.sequence for e in events if e.draft.user_id == owner] + list(extra_victims)
    erasure = AuditDraft("evt_erase", now, "erased", Actor.USER, AuditKind.ACCOUNT_DELETED,
                         detail=erasure_detail(victims if commit_to is None else list(commit_to), {"statements": 1}))
    erased = [tombstone(e, "evt_erase", now) if e.sequence in victims else e for e in events]
    return erased + [seal(erasure, len(events) + 1, events[-1].event_hash)]


def test_a_chain_with_tombstones_committed_by_a_later_erasure_verifies():
    events, _ = _chain("a", "b", "a", "b")
    erased = _erase(events, "a")
    assert verify_chain(erased).ok
    assert [e.draft.kind for e in erased[:4]] == [AuditKind.ERASED, AuditKind.SESSION_STARTED, AuditKind.ERASED, AuditKind.SESSION_STARTED]
    assert all(e.draft.user_id is None and e.draft.session_id == "erased" for e in erased if e.draft.kind is AuditKind.ERASED)


def test_erasing_another_users_event_without_committing_to_it_fails():
    events, _ = _chain("a", "b", "a", "b")
    forged = _erase(events, "a", extra_victims=(2,), commit_to=(1, 3))  # B's event 2 erased, the erasure still says 1 and 3
    check = verify_chain(forged)
    assert not check.ok and check.reason == "erasure not recorded by a later erasure event"


def test_a_tombstone_with_no_erasure_event_fails():
    events, now = _chain("a", "b")
    lonely = [tombstone(events[0], "evt_nobody", now), events[1]]
    assert not verify_chain(lonely).ok


def test_an_erasure_event_whose_count_does_not_match_fails():
    events, _ = _chain("a", "b")
    erased = _erase(events, "a")
    edited = replace(erased[-1].draft, detail=erased[-1].draft.detail.replace("erased_events=1", "erased_events=2"))
    resealed = erased[:-1] + [seal(edited, erased[-1].sequence, erased[-1].prev_hash)]
    assert not verify_chain(resealed).ok


def test_a_tombstone_after_its_erasure_event_fails():
    events, now = _chain("a", "b")
    erased = _erase(events, "a")
    late = seal(AuditDraft("evt_late", now, "s_a", Actor.USER, AuditKind.SESSION_STARTED, user_id="a"), len(erased) + 1, erased[-1].event_hash)
    assert not verify_chain([*erased, tombstone(late, "evt_erase", now)]).ok
