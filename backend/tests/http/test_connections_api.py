"""/v1/connections end to end in demo mode, offline (ADR-047). Bodies validate against contracts/connections."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from neural_ledger.adapters.inbound.http.app import create_app  # noqa: E402

from ..contract.test_contracts import validate  # noqa: E402

TOKEN = "tok-http-never-echoed"


@pytest.fixture
def client(services):
    return TestClient(create_app(services))


def test_the_whole_mcp_flow(client):
    listed = client.get("/v1/connections")
    assert listed.status_code == 200
    validate(listed.json()["data"], "connections/connections.schema.json")

    body = {"name": "Mis inversiones", "url": "https://inversiones.example.com/mcp", "token": TOKEN, "consent": True}
    validate(body, "connections/connection_create.schema.json")
    added = client.post("/v1/connections", json=body)
    assert added.status_code == 200 and TOKEN not in added.text
    validate(added.json()["data"], "connections/connection.schema.json")
    cid = added.json()["data"]["connection_id"]

    tools = client.put(f"/v1/connections/{cid}/tools", json={"enabled": ["get_portfolio"]})
    assert tools.status_code == 200
    synced = client.post(f"/v1/connections/{cid}/sync")
    assert synced.status_code == 200
    validate(synced.json()["data"], "connections/sync_result.schema.json")

    data = client.get("/v1/connections/data")
    assert data.status_code == 200 and [w["code"] for w in data.json()["warnings"]] == ["EXTERNAL_DATA"]
    validate(data.json()["data"], "outputs/connected_data.schema.json")

    assert client.delete(f"/v1/connections/{cid}").status_code == 200
    assert client.post(f"/v1/connections/{cid}/sync").status_code == 404


def test_the_bank_flow_imports_statements(client):
    start = client.post("/v1/connections/bank/start")
    assert start.status_code == 200
    validate(start.json()["data"], "connections/bank_start.schema.json")
    body = {"exchange_token": "fixture-exchange", "consent": True}
    validate(body, "connections/bank_exchange.schema.json")
    bank = client.post("/v1/connections/bank", json=body)
    assert bank.status_code == 200
    synced = client.post(f"/v1/connections/{bank.json()['data']['connection_id']}/sync")
    assert synced.status_code == 200
    validate(synced.json()["data"], "connections/sync_result.schema.json")
    assert client.get("/v1/statements").json()["data"][0]["source"] == "api"


def test_refusals_are_422_and_never_echo_the_token(client):
    refused = client.post("/v1/connections", json={"name": "x", "url": "https://127.0.0.1/mcp", "token": TOKEN, "consent": False})
    assert refused.status_code == 422 and TOKEN not in refused.text
    assert client.put("/v1/connections/nope/tools", json={"enabled": []}).status_code == 404
