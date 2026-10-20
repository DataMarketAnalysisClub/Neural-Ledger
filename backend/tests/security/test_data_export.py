"""G02 (Ley 21.719 arts. 5 and 9): a user downloads a copy of everything stored about them.

The copy holds A's data and nothing of B's, never a password, its hash, a session token or a connection secret,
matches its contract, and is audited. Without a session there is no copy; demo mode has no route."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from neural_ledger.adapters.inbound.http.app import create_app
from neural_ledger.bootstrap.container import build
from tests.conftest import make_settings
from tests.contract.test_contracts import validate

from .test_account_deletion import EMAIL_A, EMAIL_B, NAME_A, NAME_B, PASSWORD, _give_actions, _signup, _world

pytestmark = pytest.mark.security

TOKEN = "synthetic-mcp-token-export"
FINTUAL = {"email": "fintual.export@accounts.invalid", "password": "synthetic-fintual-password", "consent": True}


@pytest.fixture(params=["memory", "sqlite"])
def two_accounts(request, tmp_path):
    services, adapters, new_client = _world(tmp_path, request.param)
    a, user_a = _signup(new_client, EMAIL_A, NAME_A)
    b, user_b = _signup(new_client, EMAIL_B, NAME_B)
    _give_actions(adapters, user_a)
    _give_actions(adapters, user_b)
    added = a.post("/v1/connections", json={"name": "Inversiones", "url": "https://inversiones.example.com/mcp", "token": TOKEN, "consent": True})
    assert added.status_code == 200, added.text
    linked = a.post("/v1/investments/link", json=FINTUAL)  # the offline fixture provider issues a "fixture-" token
    assert linked.status_code == 201, linked.text
    return services, adapters, (a, user_a), (b, user_b)


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
