"""HTTP adapter smoke tests: the API is a thin translation of use cases."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from neural_ledger.adapters.inbound.http.app import create_app  # noqa: E402


@pytest.fixture
def client(services):
    return TestClient(create_app(services))


def test_health(client):
    body = client.get("/health").json()
    assert body["mode"] == "offline" and body["audit_chain_ok"] and "simulate_purchase" in body["tools"]
    assert body["pii_detector"] == "none"  # statements are redacted by the rules alone: nothing leaves the process
    assert body["server_time"].startswith("2026-10-29T12:00:00")  # the fixed demo clock, for UI countdowns


def test_forecast_and_simulation(client):
    forecast = client.get("/v1/forecast", params={"scenario": "conservative"}).json()
    assert forecast["status"] == "OK" and forecast["snapshot_id"].startswith("forecast_")
    sim = client.post("/v1/simulate-purchase", json={"amount": 400000, "installments": 12, "first_installment_month": "2026-12"})
    assert sim.status_code == 200 and sim.json()["data"]["verdict"] == "FITS_TYPICAL_ONLY"
    bad = client.post("/v1/simulate-purchase", json={"amount": 400000, "installments": 49})
    assert bad.status_code == 422 and bad.json()["field"] == "installments"


def test_confirmation_flow_over_http(client):
    plan = client.post("/v1/savings-plan", json={}).json()
    proposal = client.post("/v1/actions/proposals", json={"session_id": "h", "plan_snapshot_id": plan["snapshot_id"]})
    assert proposal.status_code == 201
    p = proposal.json()["proposal"]
    confirm = client.post(f"/v1/actions/proposals/{p['proposal_id']}/confirm", json={"session_id": "h", "terms": p["terms"]})
    auth = confirm.json()["authorization"]
    assert confirm.status_code == 201 and "action_hash" not in auth
    attack = client.post("/v1/actions/execute", json={"session_id": "h", "authorization_id": auth["authorization_id"], "requested_terms": {**p["terms"], "amount": 700000}})
    assert attack.status_code == 403 and attack.json()["reason"] == "AUTHORIZATION_MISMATCH"
    ok = client.post("/v1/actions/execute", json={"session_id": "h", "authorization_id": auth["authorization_id"]})
    assert ok.status_code == 200 and ok.json()["status"] == "EXECUTED"
    audit = client.get("/v1/audit", params={"session_id": "h"}).json()
    assert audit["chain_ok"] and any(e["blocked_reason"] == "AUTHORIZATION_MISMATCH" for e in audit["events"])
    assert {e["user_id"] for e in audit["events"]} == {"camila"}


def test_audit_reads_are_scoped_to_the_caller(client):
    client.post("/v1/chat", json={"session_id": "shared", "message": "Will I be OK in December?"}, headers={"X-User-Id": "camila"})
    diego = client.get("/v1/audit", params={"session_id": "shared"}, headers={"X-User-Id": "diego"}).json()
    camila = client.get("/v1/audit", params={"session_id": "shared"}, headers={"X-User-Id": "camila"}).json()
    assert diego["events"] == [] and diego["chain_ok"]
    assert camila["events"] and {e["user_id"] for e in camila["events"]} == {"camila"}


def test_chat(client):
    reply = client.post("/v1/chat", json={"session_id": "c", "message": "Will I be OK in December?"}).json()
    assert reply["intent"] == "forecast" and reply["verification"]["ok"]


def test_statement_upload_list_and_detail(client):
    pytest.importorskip("pymupdf")
    pytest.importorskip("pdfplumber")
    from tests.statement_samples import santander_pdf

    upload = client.post("/v1/statements", content=santander_pdf(), headers={"Content-Type": "application/pdf", "X-User-Id": "camila"})
    assert upload.status_code == 200, upload.text
    imported = upload.json()["data"]["imports"][0]
    summary = imported["statement"]
    assert summary["verified"] and summary["line_count"] == 7 and summary["account_ref"] == "****3456"
    assert imported["redaction"] == {"rules": "pii-0.1", "detector": "none", "degraded": False, "counts": {"NUMBER": 3}}

    listed = client.get("/v1/statements", headers={"X-User-Id": "camila"}).json()["data"]
    assert [s["statement_id"] for s in listed] == [summary["statement_id"]]
    detail = client.get(f"/v1/statements/{summary['statement_id']}", headers={"X-User-Id": "camila"}).json()
    assert detail["data"]["lines"][0]["description"] == {"untrusted_text": "Compra Nacional MD SHOP ONE"}

    other = client.get(f"/v1/statements/{summary['statement_id']}", headers={"X-User-Id": "diego"})
    assert other.status_code == 404 and client.get("/v1/statements", headers={"X-User-Id": "diego"}).json()["data"] == []


def test_imported_statement_reaches_the_transaction_ledger(client):
    pytest.importorskip("pymupdf")
    pytest.importorskip("pdfplumber")
    pytest.importorskip("sklearn")
    from tests.statement_samples import santander_pdf

    ledger = client.post("/v1/statements", content=santander_pdf(), headers={"Content-Type": "application/pdf", "X-User-Id": "camila"}).json()["data"]["imports"][0]["ledger"]
    assert ledger["posted"] == ledger["new"] == 7 and ledger["classifier"].startswith("naive_bayes@")

    body = client.get("/v1/transactions", headers={"X-User-Id": "camila"}).json()
    txns = body["data"]["transactions"]
    assert len(txns) == 7 and txns[0]["merchant"] == {"untrusted_text": "Compra Nacional MD SHOP ONE"}
    assert sum(t["spent"] for t in body["data"]["spending"]) == 61_080 and body["data"]["income"][0]["spent"] == 463_521
    assert client.get("/v1/transactions", headers={"X-User-Id": "diego"}).json()["data"]["transactions"] == []


def test_statement_upload_rejects_bad_files(client):
    assert client.post("/v1/statements", content=b"hello", headers={"Content-Type": "application/pdf"}).status_code == 422
    too_big = client.post("/v1/statements", content=b"%PDF", headers={"Content-Type": "application/pdf", "Content-Length": str(16 * 1024 * 1024)})
    assert too_big.status_code == 413


def test_statement_upload_limit_holds_without_content_length(client):
    """A chunked body announces no size; the endpoint must count while reading and stop at the limit.

    Before the fix the whole body was buffered and the use case answered 422 afterwards."""

    def chunks():
        for _ in range(16):
            yield b"0" * (1024 * 1024)

    response = client.post("/v1/statements", content=chunks(), headers={"Content-Type": "application/pdf"})
    assert response.status_code == 413


def test_the_user_sets_a_category_over_http(client):
    pytest.importorskip("pymupdf")
    pytest.importorskip("pdfplumber")
    pytest.importorskip("sklearn")
    from tests.statement_samples import santander_pdf

    camila = {"X-User-Id": "camila"}
    client.post("/v1/statements", content=santander_pdf(), headers={"Content-Type": "application/pdf", **camila})
    first = client.get("/v1/transactions", headers=camila).json()["data"]["transactions"][0]
    path = f"/v1/transactions/{first['txn_id']}"

    changed = client.patch(path, json={"category": "movement", "session_id": "web-1"}, headers=camila)
    assert changed.status_code == 200
    assert {k: changed.json()["data"][k] for k in ("txn_id", "category", "classifier", "confidence", "amount")} == {
        "txn_id": first["txn_id"], "category": "movement", "classifier": "user", "confidence": None, "amount": first["amount"],
    }
    assert client.get("/v1/transactions", headers=camila).json()["data"]["transactions"][0]["category"] == "movement"
    events = client.get("/v1/audit", headers=camila, params={"session_id": "web-1"}).json()["events"]
    assert [e["kind"] for e in events] == ["CATEGORY_CHANGED"]

    refused = client.patch(path, json={"category": "approved"}, headers=camila)
    assert refused.status_code == 422 and refused.json()["field"] == "category" and "movement" in refused.json()["allowed"]
    assert client.patch(path, json={"category": ["dining"]}, headers=camila).status_code == 422
    assert client.patch(path, json={"category": "dining"}, headers={"X-User-Id": "diego"}).status_code == 404
    assert client.patch("/v1/transactions/txn_nope", json={"category": "dining"}, headers=camila).status_code == 404
