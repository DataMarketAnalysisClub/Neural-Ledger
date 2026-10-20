"""The investment routes over HTTP (ADR-044): user-only link, sync and unlink for real accounts, reads in every mode,
bodies that match the contracts and never carry a credential."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from neural_ledger.adapters.inbound.http.app import create_app
from neural_ledger.bootstrap.container import build
from tests.conftest import make_settings
from tests.contract.test_contracts import validate

ORIGIN = "http://localhost:5173"
EMAIL = "investor-api@accounts.invalid"
FINTUAL_EMAIL = "mi.cuenta@fintual-user.invalid"
FINTUAL_PASSWORD = "synthetic-fintual-password"
LINK = {"email": FINTUAL_EMAIL, "password": FINTUAL_PASSWORD, "consent": True}


def _client(**overrides):
    services, adapters = build(make_settings(auth="accounts", app_origins=(ORIGIN,), **overrides))
    return TestClient(create_app(services, cors_origins=(ORIGIN,)), headers={"Origin": ORIGIN}), services, adapters


@pytest.fixture(params=["memory", "sqlite"])
def signed_in(request, tmp_path):
    overrides = {"persistence": "sqlite", "sqlite_path": str(tmp_path / "investments-api.db")} if request.param == "sqlite" else {}
    client, services, adapters = _client(**overrides)
    body = {"email": EMAIL, "password": "synthetic-password-123", "display_name": "Ana", "sandbox_acknowledged": True}
    assert client.post("/v1/auth/signup", json=body).status_code == 201
    return client, services, adapters


def _no_credentials(response) -> None:
    assert FINTUAL_PASSWORD not in response.text and FINTUAL_EMAIL not in response.text and "fixture-" not in response.text


def test_link_read_sync_and_unlink(signed_in):
    client, _, _ = signed_in
    assert client.get("/v1/investments/link").status_code == 404
    assert client.get("/v1/investments").status_code == 409  # INSUFFICIENT_DATA until an account is linked

    linked = client.post("/v1/investments/link", json=LINK)
    assert linked.status_code == 201, linked.text
    validate(linked.json(), "investments/link_outcome.schema.json")
    assert linked.json()["status"] == "LINKED" and linked.json()["link"]["email"] == "m***@fintual-user.invalid"
    _no_credentials(linked)

    overview = client.get("/v1/investments")
    assert overview.status_code == 200
    validate(overview.json(), "common/envelope.schema.json")
    validate(overview.json()["data"], "outputs/investments.schema.json")
    assert overview.json()["data"]["total_value"] == 4_511_470 and overview.json()["data"]["synthetic"] is True
    _no_credentials(overview)

    status = client.get("/v1/investments/link")
    assert status.status_code == 200 and status.json()["status"] == "LINKED"
    validate(status.json(), "investments/link_outcome.schema.json")

    synced = client.post("/v1/investments/sync")
    assert synced.status_code == 200 and synced.json()["status"] == "SYNCED"
    validate(synced.json(), "investments/link_outcome.schema.json")

    unlinked = client.delete("/v1/investments/link")
    assert unlinked.status_code == 200 and unlinked.json() == {"status": "UNLINKED", "link": None, "field": None, "message": None}
    validate(unlinked.json(), "investments/link_outcome.schema.json")
    assert client.get("/v1/investments").status_code == 409
    assert client.delete("/v1/investments/link").status_code == 404


@pytest.mark.parametrize(
    "body, field",
    [
        ({"email": FINTUAL_EMAIL, "password": FINTUAL_PASSWORD}, "consent"),
        ({**LINK, "token": "x"}, "body"),
        ({**LINK, "provider": "another"}, "provider"),
        ({**LINK, "email": 5}, "email"),
        ({**LINK, "password": ["x"]}, "password"),
    ],
)
def test_malformed_bodies_are_422_and_echo_nothing(signed_in, body, field):
    client, _, _ = signed_in
    response = client.post("/v1/investments/link", json=body)
    assert response.status_code == 422 and response.json()["field"] == field
    _no_credentials(response)


def test_declined_consent_and_invalid_email_are_link_outcomes(signed_in):
    client, _, _ = signed_in
    declined = client.post("/v1/investments/link", json={**LINK, "consent": False})
    assert declined.status_code == 422 and declined.json()["status"] == "INVALID_INPUT" and declined.json()["field"] == "consent"
    validate(declined.json(), "investments/link_outcome.schema.json")
    bad = client.post("/v1/investments/link", json={**LINK, "email": "not-an-email"})
    assert bad.status_code == 422 and bad.json()["field"] == "email" and "not-an-email" not in bad.text


def test_a_demo_persona_and_demo_mode_cannot_link():
    client, _, _ = _client()
    assert client.post("/v1/auth/demo-session", json={"persona": "camila"}).status_code == 200
    for method, path in (("post", "/v1/investments/link"), ("post", "/v1/investments/sync"), ("delete", "/v1/investments/link")):
        response = client.request(method.upper(), path, json=LINK if path.endswith("link") and method == "post" else None)
        assert response.status_code == 403 and response.json()["status"] == "READ_ONLY", path
        validate(response.json(), "investments/link_outcome.schema.json")

    services, _ = build(make_settings())  # demo mode: the X-User-Id header, no sessions
    demo = TestClient(create_app(services))
    assert demo.post("/v1/investments/link", json=LINK).status_code == 403
    assert demo.get("/v1/investments", headers={"X-User-Id": "camila"}).status_code == 409


def test_linking_is_rate_limited_like_sign_in(signed_in):
    client, _, _ = signed_in
    codes = [client.post("/v1/investments/link", json={**LINK, "consent": False}).status_code for _ in range(6)]
    assert codes[:5] == [422] * 5 and codes[5] == 429


def test_health_names_the_investment_adapter(signed_in):
    client, _, _ = signed_in
    assert client.get("/health").json()["investments"] == "fixture"


# ---- statements imported through the documents route (the path in use) ------------------------------------


def test_an_account_imports_its_statements_reads_them_and_forgets_them(signed_in):
    pytest.importorskip("pymupdf")
    from tests.investment_samples import holdings_pdf, movements_pdf

    client, _, _ = signed_in
    for content, kind in ((holdings_pdf(), "investment"), (movements_pdf(), None)):  # chosen in the Investments page, or routed
        response = client.post("/v1/documents", content=content, params={"session_id": "s-api", **({"kind": kind} if kind else {})})
        assert response.status_code == 200, response.text
        validate(response.json(), "common/envelope.schema.json")
        validate(response.json()["data"], "outputs/document_ingest.schema.json")
        assert response.json()["data"]["kind"] == "investment" and response.json()["data"]["investment"]["document"]["verified"]
    overview = client.get("/v1/investments")
    assert overview.status_code == 200 and overview.json()["data"]["total_gain"] == 49_764
    validate(overview.json()["data"], "outputs/investments.schema.json")

    removed = client.delete("/v1/investments/documents")
    assert removed.status_code == 200 and removed.json() == {"removed": 2}
    validate(removed.json(), "investments/documents_removed.schema.json")
    assert client.get("/v1/investments").status_code == 409


def test_a_demo_persona_and_demo_mode_cannot_import_or_remove_statements():
    pytest.importorskip("pymupdf")
    from tests.investment_samples import holdings_pdf

    client, _, _ = _client()
    assert client.post("/v1/auth/demo-session", json={"persona": "camila"}).status_code == 200
    for kind in ("investment", None):
        refused = client.post("/v1/documents", content=holdings_pdf(), params={"kind": kind} if kind else {})
        assert refused.status_code == 422 and refused.json()["field"] == "kind", refused.text
    assert client.delete("/v1/investments/documents").status_code == 403

    services, _ = build(make_settings())  # demo mode: no account at all
    demo = TestClient(create_app(services))
    assert demo.post("/v1/documents", content=holdings_pdf(), headers={"X-User-Id": "camila"}).status_code == 422
    assert demo.delete("/v1/investments/documents").status_code == 403
