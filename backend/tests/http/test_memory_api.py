"""ADR-048 steps 8-9 over HTTP: consent, the card's confirmation, Perfil's declaration, the view, the export and the
deletion. Identity comes from the session only; errors follow contracts/memory/memory_error.schema.json and never
echo an amount or reveal another user's resources. Memory is saved only: no financial number changes."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from neural_ledger.adapters.inbound.http.app import create_app
from neural_ledger.bootstrap.container import build
from tests.conftest import make_settings
from tests.contract.test_contracts import validate

ORIGIN = "http://localhost:3000"
KEY = "6d" * 32
PASSWORD = "synthetic-password-api"
AMOUNT = 1_234_567
SALARY = {"amount": AMOUNT, "net": True, "effective_from": "2026-11"}


class Api:
    def __init__(self, persistence: str, tmp_path) -> None:
        extra = {"persistence": "sqlite", "sqlite_path": str(tmp_path / "api.db"), "data_key": KEY} if persistence == "sqlite" else {}
        self.services, self.adapters = build(make_settings(auth="accounts", app_origins=(ORIGIN,), **extra))
        self.app = create_app(self.services, cors_origins=(ORIGIN,), rate_limits=())

    def client(self) -> TestClient:
        return TestClient(self.app, headers={"Origin": ORIGIN})

    def signup(self, email: str) -> tuple[TestClient, str]:
        client = self.client()
        response = client.post("/v1/auth/signup", json={"email": email, "password": PASSWORD, "display_name": "Ana", "sandbox_acknowledged": True})
        assert response.status_code == 201, response.text
        return client, response.json()["user_id"]

    def persona(self, name: str = "camila") -> TestClient:
        client = self.client()
        assert client.post("/v1/auth/demo-session", json={"persona": name}).status_code == 200
        return client


@pytest.fixture(params=["memory", "sqlite"])
def api(request, tmp_path) -> Api:
    return Api(request.param, tmp_path)


def _grant(client: TestClient) -> dict:
    response = client.put("/v1/memory/consent", json={"consent": "granted"})
    assert response.status_code == 200, response.text
    return response.json()


def _card(client: TestClient, message: str = "Mi sueldo líquido es 1.234.567 desde noviembre") -> dict:
    reply = client.post("/v1/chat", json={"session_id": "s_api", "message": message}).json()
    validate(reply, "chat/chat_reply.schema.json")
    assert reply["intent"] == "report_income_change" and reply["tools_called"] == ["propose_income_change"], reply
    return reply


def _error(response, status: str, code: int) -> dict:
    assert response.status_code == code, response.text
    body = response.json()
    validate(body, "memory/memory_error.schema.json")
    assert body["status"] == status and str(AMOUNT) not in response.text
    return body


# ---- the whole journey ------------------------------------------------------------------------------------

def test_consent_card_confirm_view_export_delete(api):
    client, user_id = api.signup("ana.api@accounts.invalid")
    forecast_before = client.get("/v1/forecast").json()
    consent = client.get("/v1/memory/consent").json()
    validate(consent, "memory/memory_consent.schema.json")
    assert consent == {"consent": "missing", "consent_generation": 0, "memory_revision": 0}
    granted = _grant(client)
    validate(granted, "memory/memory_consent.schema.json")
    assert granted == {"consent": "granted", "consent_generation": 1, "memory_revision": 0, "changed": True}
    assert _grant(client)["changed"] is False  # idempotent

    reply = _card(client)
    card = reply["pending_memory_proposal"]
    validate(card, "memory/income_proposal.schema.json")
    assert (card["status"], card["candidates"], card["effective_from"]["pay_month"]) == ("READY", [AMOUNT], "2026-11")
    assert reply["memory_dependency"] == {"consent_generation": 1, "memory_revision": 0}
    assert "saved" in reply["text"] and "does not change your projections" in reply["text"] and reply["verification"]["ok"]
    assert client.get("/v1/memory").json()["items"] == []  # preparing saved nothing

    confirmed = client.post(f"/v1/memory/proposals/{card['proposal_id']}/confirm", json={"salary_net": SALARY, "expected_version": 0, "session_id": "s_x"})
    assert confirmed.status_code == 200, confirmed.text
    view = confirmed.json()
    validate(view, "memory/memory_view.schema.json")
    (item,) = view["items"]
    assert item["versions"] == 1 and item["current"] is None and item["upcoming"]["value"]["salary_net"]["amount"] == AMOUNT
    assert item["upcoming"]["origin"] == {"kind": "chat", "session_id": "s_api", "message_id": item["upcoming"]["origin"]["message_id"]}
    check = item["check"]
    assert (check["numeric_effect"], check["reasons"], check["params_version"]) == ("saved_only", [], "salary-check-0.1")

    edited = client.put("/v1/profile/income", json={"salary_net": {**SALARY, "amount": 1_300_000}, "expected_version": 1})
    assert edited.status_code == 200 and edited.json()["items"][0]["versions"] == 2
    exported = client.get("/v1/memory/export").json()
    validate(exported, "memory/memory_export.schema.json")
    assert [(d["version"], d["source"]) for d in exported["declarations"]] == [(1, "chat"), (2, "profile")]
    assert client.get("/v1/forecast").json() == forecast_before  # saved only: no number moved

    deleted = client.delete(f"/v1/memory/{item['chain_id']}")
    assert deleted.status_code == 200
    validate(deleted.json(), "memory/memory_deletion.schema.json")
    assert deleted.json() == {"chain_id": item["chain_id"], "deleted_versions": 2, "revoked_proposals": 0}
    assert client.get("/v1/memory").json()["items"] == [] and client.get("/v1/memory/export").json()["declarations"] == []
    assert client.get("/v1/memory/consent").json()["memory_revision"] == 3
    kinds = [e["kind"] for e in client.get("/v1/audit").json()["events"]]
    assert {"MEMORY_CONSENT_CHANGED", "MEMORY_CONFIRMED", "MEMORY_DELETED"} <= set(kinds)
    assert user_id not in client.get("/v1/memory").text  # the owner is never part of the view


def test_without_consent_the_view_lists_declarations_without_a_check(api):
    client, _ = api.signup("bea.api@accounts.invalid")
    _grant(client)
    assert client.put("/v1/profile/income", json={"salary_net": SALARY, "expected_version": 0}).status_code == 200
    assert client.put("/v1/memory/consent", json={"consent": "revoked"}).json()["changed"] is True
    view = client.get("/v1/memory").json()
    assert view["consent"] == "revoked" and view["items"][0]["check"] is None and view["items"][0]["upcoming"] is not None
    assert len(client.get("/v1/memory/export").json()["declarations"]) == 1  # export and deletion need no consent
    reply = client.post("/v1/chat", json={"session_id": "s_api", "message": "Mi sueldo líquido es 1.234.567"}).json()
    assert reply["pending_memory_proposal"] is None and "permission" in reply["text"]
    _error(client.put("/v1/profile/income", json={"salary_net": SALARY, "expected_version": 1}), "CONSENT_REQUIRED", 428)


# ---- errors: precedence, ownership, staleness --------------------------------------------------------------

def test_errors_follow_the_contract_and_its_precedence(api):
    client, _ = api.signup("carla.api@accounts.invalid")
    other, _ = api.signup("dani.api@accounts.invalid")
    _grant(client)
    card = _card(client)["pending_memory_proposal"]
    url = f"/v1/memory/proposals/{card['proposal_id']}/confirm"
    _error(other.post(url, json={"salary_net": SALARY, "expected_version": 0}), "NOT_FOUND", 404)  # another user's
    _error(client.post("/v1/memory/proposals/prp_nope/confirm", json={"salary_net": SALARY, "expected_version": 0}), "NOT_FOUND", 404)
    _error(other.delete("/v1/memory/chn_unknown"), "NOT_FOUND", 404)
    assert client.post(url, json={"salary_net": SALARY, "expected_version": 0}).status_code == 200
    _error(client.post(url, json={"salary_net": SALARY, "expected_version": 0}), "PROPOSAL_USED", 409)
    stale = _card(client, "Me subieron el sueldo a 1.300.000")["pending_memory_proposal"]
    assert client.put("/v1/profile/income", json={"salary_net": SALARY, "expected_version": 1}).status_code == 200
    _error(client.post(f"/v1/memory/proposals/{stale['proposal_id']}/confirm", json={"salary_net": SALARY, "expected_version": 1}), "PROPOSAL_STALE", 409)
    _error(client.put("/v1/profile/income", json={"salary_net": SALARY, "expected_version": 1}), "VERSION_CONFLICT", 409)
    expiring = _card(client, "Ahora gano 1.400.000")["pending_memory_proposal"]
    api.adapters.clock.advance(minutes=30)  # exactly the PP_0_1 TTL
    _error(client.post(f"/v1/memory/proposals/{expiring['proposal_id']}/confirm", json={"salary_net": SALARY, "expected_version": 2}), "PROPOSAL_STALE", 409)


@pytest.mark.parametrize(
    "body, field",
    [
        ({"salary_net": {**SALARY, "amount": True}, "expected_version": 0}, "salary_net.amount"),
        ({"salary_net": {**SALARY, "amount": "1234567"}, "expected_version": 0}, "salary_net.amount"),
        ({"salary_net": {**SALARY, "amount": 1234567.0}, "expected_version": 0}, "salary_net.amount"),
        ({"salary_net": SALARY, "expected_version": 0, "user_id": "someone"}, "user_id"),
        ({"salary_net": {**SALARY, "extra": 1}, "expected_version": 0}, "salary_net.extra"),
        ({"salary_net": SALARY, "expected_version": False}, "expected_version"),
    ],
)
def test_a_malformed_body_is_422_with_its_field_and_no_echo(api, body, field):
    client, _ = api.signup("eva.api@accounts.invalid")
    _grant(client)
    assert _error(client.put("/v1/profile/income", json=body), "INVALID_INPUT", 422)["field"] == field
    assert client.get("/v1/memory/export").json()["declarations"] == []


@pytest.mark.parametrize("body", [{"consent": "missing"}, {"consent": True}, {"consent": "granted", "user_id": "x"}, []])
def test_a_malformed_consent_update_is_422(api, body):
    client, _ = api.signup("fran.api@accounts.invalid")
    response = client.put("/v1/memory/consent", json=body)
    _error(response, "INVALID_INPUT", 422)
    assert client.get("/v1/memory/consent").json()["consent"] == "missing"


def test_a_persona_writes_nothing_and_sees_no_memory(api):
    persona = api.persona()
    before = api.adapters.audit_log.events()
    _error(persona.put("/v1/memory/consent", json={"consent": "granted"}), "PERSONA_READ_ONLY", 403)
    _error(persona.put("/v1/profile/income", json={"salary_net": SALARY, "expected_version": 0}), "PERSONA_READ_ONLY", 403)
    _error(persona.post("/v1/memory/proposals/prp_x/confirm", json={"salary_net": SALARY, "expected_version": 0}), "PERSONA_READ_ONLY", 403)
    _error(persona.delete("/v1/memory/chn_x"), "PERSONA_READ_ONLY", 403)
    assert persona.get("/v1/memory").json()["items"] == [] and persona.get("/v1/memory/export").json()["declarations"] == []
    reply = persona.post("/v1/chat", json={"session_id": "s_p", "message": "Mi sueldo líquido es 1.234.567"}).json()
    assert reply["pending_memory_proposal"] is None
    assert not [e for e in api.adapters.audit_log.events() if e not in before and e.draft.kind.value.startswith("MEMORY_")]
    assert api.services.memory.consent("camila").consent.value == "missing"


def test_a_structurally_invalid_body_wins_over_the_persona_check(api):
    persona = api.persona()
    _error(persona.put("/v1/profile/income", json={"salary_net": {**SALARY, "amount": True}, "expected_version": 0}), "INVALID_INPUT", 422)


def test_memory_writes_need_the_apps_origin_and_a_session(api):
    client, _ = api.signup("gabi.api@accounts.invalid")
    foreign = client.put("/v1/memory/consent", json={"consent": "granted"}, headers={"Origin": "https://evil.example"})
    assert foreign.status_code == 403 and foreign.json()["status"] == "ORIGIN_REJECTED"
    anonymous = api.client()
    for method, path in (("GET", "/v1/memory"), ("GET", "/v1/memory/export"), ("PUT", "/v1/memory/consent"), ("DELETE", "/v1/memory/chn_x")):
        assert anonymous.request(method, path, json={"consent": "granted"}).status_code == 401
    assert client.get("/v1/memory/consent").json()["consent"] == "missing"


def test_demo_mode_has_no_writable_memory(tmp_path):
    services, _ = build(make_settings())
    client = TestClient(create_app(services))
    _error(client.put("/v1/memory/consent", json={"consent": "granted"}), "PERSONA_READ_ONLY", 403)
    _error(client.put("/v1/memory/consent", json={"consent": "granted"}, headers={"X-User-Id": "someone"}), "PERSONA_READ_ONLY", 403)
    assert client.get("/v1/memory").json()["items"] == []
