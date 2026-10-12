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
    assert body["server_time"].startswith("2026-10-29T12:00:00")  # the fixed demo clock, for UI countdowns


def test_forecast_and_simulation(client):
    forecast = client.get("/v1/forecast", params={"scenario": "conservative"}).json()
    assert forecast["status"] == "OK" and forecast["snapshot_id"].startswith("forecast_")
    sim = client.post("/v1/simulate-purchase", json={"amount": 400000, "installments": 12, "first_installment_month": "2026-12"})
    assert sim.status_code == 200 and sim.json()["data"]["verdict"] == "FITS_TYPICAL_ONLY"
    bad = client.post("/v1/simulate-purchase", json={"amount": 400000, "installments": 7})
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
