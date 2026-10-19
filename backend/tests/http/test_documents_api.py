"""ADR-039 over HTTP: drop a file, read the spending check-in and the receipts. The body is the raw file."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from neural_ledger.adapters.inbound.http.app import create_app  # noqa: E402
from tests.receipt_samples import boleta_pdf  # noqa: E402
from tests.statement_samples import santander_xlsx  # noqa: E402


@pytest.fixture
def system():
    from neural_ledger.bootstrap.container import build
    from tests.conftest import make_settings

    return build(make_settings(fixed_now="2026-10-19T12:00:00-03:00"))  # inside the October cycle, after the boleta


@pytest.fixture
def client(services):
    return TestClient(create_app(services))


def test_a_boleta_dropped_on_the_copilot(client):
    response = client.post("/v1/documents", params={"session_id": "s-web"}, content=boleta_pdf(), headers={"Content-Type": "application/pdf"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "OK" and body["data"]["kind"] == "receipt"
    assert [s["key"] for s in body["data"]["steps"]] == ["read", "route", "verify", "redact", "duplicate", "categorize", "match", "spending"]
    assert body["data"]["receipt"]["issuer"] == {"untrusted_text": "SUPERMERCADO LOS ANDES SPA"}
    assert body["data"]["spending"]["per_day"] == 80_637

    spending = client.get("/v1/spending").json()
    assert spending["data"]["check"]["left"] == 887_010 and spending["data"]["latest_receipt"]["total"] == 12_990
    receipts = client.get("/v1/receipts").json()
    assert [r["total"] for r in receipts["data"]] == [12_990]


def test_a_spreadsheet_dropped_on_the_copilot_is_a_statement(client):
    body = client.post("/v1/documents", content=santander_xlsx()).json()
    assert body["status"] == "OK" and body["data"]["kind"] == "statement" and body["data"]["statement"]["imports"]


def test_an_empty_or_unknown_file_is_refused(client):
    assert client.post("/v1/documents", content=b"").status_code == 422
    unknown = client.post("/v1/documents", content=b"just some text")
    assert unknown.status_code == 422 and unknown.json()["field"] == "file"


def test_an_oversized_upload_is_refused_before_it_is_read(client):
    response = client.post("/v1/documents", content=b"x" * (15 * 1024 * 1024 + 1))
    assert response.status_code == 413


def test_the_user_corrects_a_receipt_over_http(client):
    client.post("/v1/documents", content=boleta_pdf())
    rid = client.get("/v1/receipts").json()["data"][0]["receipt_id"]
    ok = client.patch(f"/v1/receipts/{rid}", json={"session_id": "s", "total": 12990, "issued_on": "2026-10-16"})
    assert ok.status_code == 200 and ok.json()["data"]["corrected"] is True
    assert client.patch(f"/v1/receipts/{rid}", json={"total": 0}).status_code == 422
    assert client.patch("/v1/receipts/rcpt_nope", json={"total": 1}).status_code == 404


def test_the_user_confirms_an_expense_over_http(client):
    reply = client.post("/v1/chat", json={"session_id": "s-e", "message": "Pagué 8.000 en un taxi en efectivo"}).json()
    pid = reply["pending_expense"]["proposal_id"]
    ok = client.post(f"/v1/expenses/{pid}/confirm", json={"session_id": "s-e", "payment": "cash", "category": "transport"})
    assert ok.status_code == 200 and ok.json()["data"]["source"] == "manual" and ok.json()["data"]["payment"] == "cash"
    assert client.post("/v1/expenses/exp_nope/confirm", json={"payment": "cash"}).status_code == 404
