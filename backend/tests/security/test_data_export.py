"""G02 (Ley 21.719 arts. 5 and 9): a user downloads a copy of everything stored about them.

The copy holds A's data and nothing of B's, memory, proposals and authorizations included, never a password, its hash, a session
token, a connection secret or an authorization's signature, matches its contract, and is audited. Every table an account deletion
empties is in the copy or listed below with the reason it is not. Without a session there is no copy; demo mode has no route."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from neural_ledger.adapters.inbound.http.app import create_app
from neural_ledger.adapters.outbound.persistence.sqlite import _ERASE_ACCOUNT_SQL, _ERASE_SQL
from neural_ledger.bootstrap.container import build
from neural_ledger.domain.shared.serialization import to_primitive
from tests.conftest import make_settings
from tests.contract.test_contracts import validate

from .test_account_deletion import EMAIL_A, EMAIL_B, NAME_A, NAME_B, PASSWORD, _give_actions, _signup, _world

pytestmark = pytest.mark.security

TOKEN = "synthetic-mcp-token-export"
FINTUAL = {"email": "fintual.export@accounts.invalid", "password": "synthetic-fintual-password", "consent": True}


# Every table an account deletion empties (sqlite._ERASE_SQL and _ERASE_ACCOUNT_SQL), and where its rows are in the copy.
IN_THE_COPY: dict[str, Callable[[dict[str, Any]], list]] = {
    "user_accounts": lambda body: [body["account"]] if body["account"] else [],
    "user_profiles": lambda body: [body["profile"]] if body["profile"] else [],
    "statements": lambda body: body["statements"],
    "transactions": lambda body: body["transactions"],
    "receipts": lambda body: body["receipts"],
    "connections": lambda body: body["connections"],
    "connection_results": lambda body: [r for c in body["connections"] for r in c["results"]],
    "user_memory": lambda body: body["memory"]["declarations"]["declarations"],
    "memory_state": lambda body: [body["memory"]["consent"]],
    "savings_rules": lambda body: body["savings_rules"],
    "proposals": lambda body: body["proposals"],
    "authorizations": lambda body: body["authorizations"],
    "investment_links": lambda body: [body["investments"]["link"]] if body["investments"]["link"] else [],
    # Only the latest sync: older ones (up to MAX_SNAPSHOTS) are erased but not yet in the copy.
    "investment_snapshots": lambda body: [body["investments"]["latest_snapshot"]] if body["investments"]["latest_snapshot"] else [],
    "investment_documents": lambda body: body["investments"]["documents"],
}
LEFT_OUT = {
    "sessions": "a session row is a credential (the token digest), never personal data to hand out",
    "memory_proposals": "a pending memory proposal expires within PP_0_1.proposal_ttl_seconds; once confirmed it is a declaration",
}


def _two_accounts(tmp_path, persistence: str):
    services, adapters, new_client = _world(tmp_path, persistence)
    a, user_a = _signup(new_client, EMAIL_A, NAME_A)
    b, user_b = _signup(new_client, EMAIL_B, NAME_B)
    _give_actions(adapters, user_a)
    _give_actions(adapters, user_b)
    added = a.post("/v1/connections", json={"name": "Inversiones", "url": "https://inversiones.example.com/mcp", "token": TOKEN, "consent": True})
    assert added.status_code == 200, added.text
    linked = a.post("/v1/investments/link", json=FINTUAL)  # the offline fixture provider issues a "fixture-" token
    assert linked.status_code == 201, linked.text
    return services, adapters, (a, user_a), (b, user_b)


@pytest.fixture(params=["memory", "sqlite"])
def two_accounts(request, tmp_path):
    return _two_accounts(tmp_path, request.param)


def _confirm(client, adapters, user_id: str) -> str:
    """The user confirms the pending proposal _give_actions stored, through the UI endpoint (the only way)."""
    proposal = adapters.actions_repo.get_proposal(f"prop_{user_id}")
    response = client.post(f"/v1/actions/proposals/{proposal.proposal_id}/confirm", json={"session_id": "s1", "terms": to_primitive(proposal.terms)})
    assert response.status_code == 201 and response.json()["status"] == "CONFIRMED", response.text
    return response.json()["authorization"]["authorization_id"]


def test_the_copy_is_all_of_a_and_nothing_of_b(two_accounts):
    services, _, (a, user_a), (_, user_b) = two_accounts

    response = a.get("/v1/me/export")

    assert response.status_code == 200, response.text
    assert response.headers["content-disposition"].startswith('attachment; filename="neural-ledger-data-')
    body = response.json()
    validate(body, "auth/data_export.schema.json")
    assert body["user_id"] == user_a and body["account"]["email"] == EMAIL_A
    assert body["profile"]["display_name"] == NAME_A
    assert body["statements"] and body["transactions"] and len(body["receipts"]) == 1
    assert [c["name"] for c in body["connections"]] == ["Inversiones"]
    assert [r["user_id"] for r in body["savings_rules"]] == [user_a]
    assert body["investments"]["link"]["provider"] and body["investments"]["latest_snapshot"]
    # Memory (ADR-048): what a deletion erases, with or without consent; every version, never another user's.
    assert [d["chain_id"] for d in body["memory"]["declarations"]["declarations"]] == [f"chn_{user_a}"]
    assert body["memory"]["consent"] == {"consent": "missing", "consent_generation": 0, "memory_revision": 0}
    assert {e["user_id"] for e in body["audit_events"]} == {user_a}
    assert body["audit_events"][-1]["kind"] == "DATA_EXPORTED"  # audited first, so the copy shows its own event
    for leaked in (user_b, EMAIL_B, NAME_B, PASSWORD, TOKEN, "scrypt$", FINTUAL["password"], '"token"', "fixture-"):
        assert leaked not in response.text
    assert services.audit.verify().ok


def test_exporting_writes_one_audit_event_and_nothing_else(two_accounts):
    _, adapters, (a, user_a), _ = two_accounts
    before = adapters.audit_log.events()

    a.get("/v1/me/export")

    after = adapters.audit_log.events()
    assert after[: len(before)] == before
    assert [(e.draft.kind.value, e.draft.user_id, e.draft.detail) for e in after[len(before):]] == [("DATA_EXPORTED", user_a, None)]


def test_no_copy_without_a_session_or_after_a_deletion(two_accounts):
    _, _, (a, _), _ = two_accounts
    assert a.request("DELETE", "/v1/account", json={"confirm": "DELETE", "password": PASSWORD}).status_code == 200
    assert a.get("/v1/me/export").status_code == 401


def test_demo_mode_has_no_export():
    services, _ = build(make_settings())
    assert TestClient(create_app(services)).get("/v1/me/export").status_code == 404


def test_a_confirmed_proposal_and_its_authorization_are_in_the_copy_without_the_signature(two_accounts):
    _, adapters, (a, user_a), (b, user_b) = two_accounts
    authorization_id = _confirm(a, adapters, user_a)
    _confirm(b, adapters, user_b)
    signature = adapters.actions_repo.get_authorization(authorization_id).action_hash

    response = a.get("/v1/me/export")

    body = response.json()
    validate(body, "auth/data_export.schema.json")
    assert [(p["proposal_id"], p["user_id"], p["status"]) for p in body["proposals"]] == [(f"prop_{user_a}", user_a, "confirmed")]
    [authorization] = body["authorizations"]
    assert authorization["authorization_id"] == authorization_id and authorization["proposal_id"] == f"prop_{user_a}"
    assert authorization["terms"] == body["proposals"][0]["terms"] and authorization["terms"]["amount"] == 50_000
    assert authorization["consumed_at"] is None
    assert "action_hash" not in authorization and signature not in response.text
    assert user_b not in response.text


def test_every_table_a_deletion_empties_is_in_the_copy_or_left_out_for_a_reason():
    erased = set(_ERASE_SQL) | set(_ERASE_ACCOUNT_SQL)
    assert not set(IN_THE_COPY) & set(LEFT_OUT)
    assert erased == set(IN_THE_COPY) | set(LEFT_OUT), "a new erased table needs a place in the export (or a reason in LEFT_OUT)"


def test_every_row_a_deletion_would_erase_has_its_place_in_the_copy(tmp_path):
    _, adapters, (a, user_a), _ = _two_accounts(tmp_path, "sqlite")
    _confirm(a, adapters, user_a)
    body = a.get("/v1/me/export").json()
    db = adapters.actions_repo._db
    for table, section in IN_THE_COPY.items():
        (rows,) = db.fetchone(f"SELECT COUNT(*) FROM {table} WHERE user_id = ?", (user_a,))  # table names are the constants above
        assert len(section(body)) >= rows, f"{table}: {rows} rows erased, {len(section(body))} in the copy"
    for table in ("proposals", "authorizations", "savings_rules", "user_memory", "connections", "investment_links", "receipts"):
        assert db.fetchone(f"SELECT COUNT(*) FROM {table} WHERE user_id = ?", (user_a,))[0] > 0, table  # the check is not vacuous
