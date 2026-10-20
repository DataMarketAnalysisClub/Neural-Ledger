"""Read-only connections through the use cases (ADR-047), offline: the synthetic MCP server and bank, memory and SQLite."""

from __future__ import annotations

import pytest

from neural_ledger.bootstrap.container import build
from neural_ledger.domain.shared.serialization import to_primitive

from ..conftest import make_settings

USER = "camila"
URL = "https://inversiones.example.com/mcp"


@pytest.fixture(params=["memory", "sqlite"])
def system(request, tmp_path):
    extra = {"persistence": "sqlite", "sqlite_path": str(tmp_path / "nl.db"), "data_key": "11" * 32} if request.param == "sqlite" else {}
    return build(make_settings(**extra))


def add(services, **overrides):
    args = {"name": "Mis inversiones", "url": URL, "token": "tok-secret-123", "consent": True, **overrides}
    return services.connections.add_mcp(USER, "s-conn", args["name"], args["url"], args["token"], args["consent"])


def test_adding_lists_the_tools_and_blocks_what_could_write(system):
    services, _ = system
    added = add(services)
    assert added.ok
    tools = {t.name: t.blocked for t in added.data.tools}
    assert tools == {"get_portfolio": None, "get_contributions": None, "get_fund": "NEEDS_ARGUMENTS", "invest": "WRITE_VERB"}
    assert added.data.host == "inversiones.example.com"
    assert "tok-secret-123" not in str(to_primitive(added))


def test_a_blocked_tool_cannot_be_enabled(system):
    services, _ = system
    cid = add(services).data.connection_id
    refused = services.connections.set_tools(USER, "s-conn", cid, ["get_portfolio", "invest"])
    assert refused.status.value == "INVALID_INPUT"
    assert services.connections.set_tools(USER, "s-conn", cid, ["nope"]).status.value == "INVALID_INPUT"
    assert services.connections.list(USER).data.connections[0].tools[0].enabled is False  # nothing changed


def test_sync_stores_redacted_answers_the_agent_reads_with_a_warning(system):
    services, _ = system
    cid = add(services).data.connection_id
    services.connections.set_tools(USER, "s-conn", cid, ["get_portfolio"])
    synced = services.connections.sync(USER, "s-conn", cid)
    assert synced.ok and [r.tool for r in synced.data.results] == ["get_portfolio"]
    data = services.connections.connected_data(USER)
    assert data.ok
    [source] = data.data.connections
    assert source.name == {"untrusted_text": "Mis inversiones"}
    assert '"balance":1850000' in source.results[0].content["untrusted_text"]
    facts = {f.key: f for f in data.facts}
    assert facts[f"external.{cid}.get_portfolio.goals.0.balance"].unit == "CLP"
    assert [w.code for w in data.warnings] == ["EXTERNAL_DATA"]


def test_only_the_tools_the_user_enabled_are_called(system):
    services, _ = system
    cid = add(services).data.connection_id
    synced = services.connections.sync(USER, "s-conn", cid)
    assert synced.ok and synced.data.results == ()
    assert services.connections.connected_data(USER).facts == ()


def test_consent_and_a_name_are_required_and_http_is_refused(system):
    services, _ = system
    assert add(services, consent=False).message.startswith("the user must agree")
    assert add(services, name="  ").status.value == "INVALID_INPUT"
    refused = add(services, url="http://inversiones.example.com/mcp")
    assert refused.status.value == "INVALID_INPUT" and "NOT_HTTPS" in refused.message
    assert services.connections.list(USER).data.connections == ()


def test_another_users_connection_is_not_found(system):
    services, _ = system
    cid = add(services).data.connection_id
    assert services.connections.sync("diego", "s-conn", cid).missing == ("connection",)
    assert services.connections.remove("diego", "s-conn", cid).missing == ("connection",)
    assert services.connections.list("diego").data.connections == ()


def test_removing_deletes_the_answers(system):
    services, adapters = system
    cid = add(services).data.connection_id
    services.connections.set_tools(USER, "s-conn", cid, ["get_portfolio"])
    services.connections.sync(USER, "s-conn", cid)
    assert services.connections.remove(USER, "s-conn", cid).ok
    assert services.connections.connected_data(USER).missing == ("connection",)
    kinds = [e.draft.kind.value for e in adapters.audit_log.events() if e.draft.kind.value.startswith("CONNECTION_")]
    assert kinds == ["CONNECTION_ADDED", "CONNECTION_UPDATED", "CONNECTION_SYNCED", "CONNECTION_REMOVED"]


def test_the_bank_first_sync_is_stored_unverified_then_later_syncs_reconcile(system):
    services, adapters = system
    assert services.connections.bank_start(USER).data.widget_token is None  # fixture: no widget
    bank = services.connections.connect_bank(USER, "s-conn", "fixture-exchange", True)
    assert bank.ok and bank.data.kind == "bank"
    first = services.connections.sync(USER, "s-conn", bank.data.connection_id)
    assert first.ok
    [imported] = first.data.statements.imports
    assert imported.statement.source == "api" and imported.statement.verified is False
    assert "STATEMENT_UNVERIFIED" in [w.code for w in first.warnings]

    adapters.clock.advance(days=20)  # new movements in the synthetic calendar
    second = services.connections.sync(USER, "s-conn", bank.data.connection_id)
    assert second.ok
    [later] = second.data.statements.imports
    assert later.statement.verified is True and later.ledger.posted > 0


def test_a_bank_sync_with_nothing_new_imports_nothing(system):
    services, _ = system
    cid = services.connections.connect_bank(USER, "s-conn", "fixture-exchange", True).data.connection_id
    services.connections.sync(USER, "s-conn", cid)
    again = services.connections.sync(USER, "s-conn", cid)
    assert again.ok and again.data.statements is None


def test_off_mode_refuses_every_write(tmp_path):
    services, _ = build(make_settings(connectors="live", deployment="deployed", data_key="22" * 32, persistence="sqlite", sqlite_path=str(tmp_path / "d.db")))
    assert services.connections.list(USER).data.mode == "off"
    assert add(services).status.value == "INVALID_INPUT"
    assert services.connections.connect_bank(USER, "s", "x", True).status.value == "INVALID_INPUT"
