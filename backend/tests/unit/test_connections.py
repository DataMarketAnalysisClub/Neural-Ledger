"""Read-only connections (ADR-047): which tools can be enabled, which addresses can be called, what the agent reads.

Every name, account and number here is fictional.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from neural_ledger.domain.connections.bank import BankAccount, BankMovement, dump_state, load_state, statement_from_sync
from neural_ledger.domain.connections.model import (
    MAX_TEXT,
    RemoteTool,
    TargetBlock,
    ToolBlock,
    check_target,
    external_facts,
    parse_tools,
    snapshot_content,
    tool_block,
)
from neural_ledger.domain.statements.model import IssueCode, reconcile


def tool(name: str, read_only: bool | None = True, destructive: bool | None = None, required: tuple[str, ...] = ()) -> RemoteTool:
    return RemoteTool(name, "", read_only, destructive, required)


@pytest.mark.parametrize(
    ("remote", "block"),
    [
        (tool("get_portfolio"), None),
        (tool("listGoals"), None),
        (tool("get_transfers"), None),  # a noun, not the verb
        (tool("get_portfolio", read_only=None), ToolBlock.NOT_READ_ONLY),
        (tool("get_portfolio", read_only=False), ToolBlock.NOT_READ_ONLY),
        (tool("get_portfolio", destructive=True), ToolBlock.DESTRUCTIVE),
        (tool("create_transfer"), ToolBlock.WRITE_VERB),  # declares read-only, but its name says otherwise
        (tool("sellShares"), ToolBlock.WRITE_VERB),
        (tool("rescatar-fondo"), ToolBlock.WRITE_VERB),
        (tool("Invertir"), ToolBlock.WRITE_VERB),
        (tool("get_fund", required=("fund_id",)), ToolBlock.NEEDS_ARGUMENTS),
    ],
)
def test_tool_block(remote: RemoteTool, block: ToolBlock | None) -> None:
    assert tool_block(remote) is block


def test_parse_tools_reads_hints_and_skips_malformed_entries() -> None:
    listed = [
        {"name": "get_goals", "description": "Goals", "annotations": {"readOnlyHint": True}, "inputSchema": {"type": "object"}},
        {"name": "get_goals", "annotations": {"readOnlyHint": False}},  # a repeated name keeps the first
        {"name": "buy", "annotations": {"readOnlyHint": "yes"}, "inputSchema": {"required": ["fund"]}},
        {"description": "no name"},
        "not an object",
    ]
    tools = parse_tools(listed)
    assert [t.name for t in tools] == ["get_goals", "buy"]
    assert tools[0].block is None
    assert tools[1].read_only_hint is None  # a hint that is not a boolean counts as not given
    assert tools[1].required_args == ("fund",)


def test_parse_tools_masks_personal_data_in_descriptions() -> None:
    [only] = parse_tools([{"name": "get_me", "description": "Cuenta de juan.perez@mail.cl", "annotations": {"readOnlyHint": True}}])
    assert "juan.perez" not in only.description


@pytest.mark.parametrize(
    ("url", "addresses", "block"),
    [
        ("https://mcp.example.com/mcp", ["93.184.216.34"], None),
        ("https://mcp.example.com/mcp", ["2606:2800:220:1:248:1893:25c8:1946"], None),
        ("http://mcp.example.com/mcp", ["93.184.216.34"], TargetBlock.NOT_HTTPS),
        ("https://user:pw@mcp.example.com/", ["93.184.216.34"], TargetBlock.CREDENTIALS_IN_URL),
        ("https://localhost/mcp", ["127.0.0.1"], TargetBlock.PRIVATE_ADDRESS),
        ("https://metadata/", ["169.254.169.254"], TargetBlock.PRIVATE_ADDRESS),
        ("https://intranet/", ["10.0.0.5"], TargetBlock.PRIVATE_ADDRESS),
        ("https://intranet/", ["::ffff:192.168.1.1"], TargetBlock.PRIVATE_ADDRESS),  # IPv4 hidden in IPv6
        ("https://mixed.example.com/", ["93.184.216.34", "10.0.0.5"], TargetBlock.PRIVATE_ADDRESS),  # any private one refuses
        ("https://nowhere.example.com/", [], TargetBlock.UNRESOLVED),
        ("ftp://mcp.example.com/", ["93.184.216.34"], TargetBlock.MALFORMED),
        ("https://mcp.example.com:99999/", ["93.184.216.34"], TargetBlock.MALFORMED),
        ("not a url", [], TargetBlock.MALFORMED),
    ],
)
def test_check_target(url: str, addresses: list[str], block: TargetBlock | None) -> None:
    assert check_target(url, addresses, allow_private=False) is block


def test_local_development_may_call_localhost_over_http() -> None:
    assert check_target("http://localhost:8765/mcp", ["127.0.0.1"], allow_private=True) is None
    assert check_target("http://user:pw@localhost/", ["127.0.0.1"], allow_private=True) is TargetBlock.CREDENTIALS_IN_URL


def test_snapshot_redacts_strings_and_keeps_numbers() -> None:
    content = snapshot_content({"owner": "Transf a JUAN PEREZ", "rut": "11.111.111-1", "balance": 1_250_000, "currency": "CLP"})
    stored = json.loads(content)
    assert "JUAN" not in content and "11.111.111" not in content
    assert stored["balance"] == 1_250_000


def test_a_large_answer_is_cut_and_then_yields_no_facts() -> None:
    content = snapshot_content({"rows": [{"amount": i, "note": "x" * 50} for i in range(500)]})
    assert len(content) <= MAX_TEXT
    assert external_facts("cn_1", "get_rows", content) == ()


def test_external_facts_take_the_currency_their_object_names() -> None:
    content = snapshot_content({"goals": [{"name": "Viaje", "balance": 1_250_000, "currency": "CLP"}, {"name": "Casa", "units": 3_500}]})
    facts = {f.key: f for f in external_facts("cn_1", "get_goals", content)}
    assert facts["external.cn_1.get_goals.goals.0.balance"].value == 1_250_000
    assert facts["external.cn_1.get_goals.goals.0.balance"].unit == "CLP"
    assert facts["external.cn_1.get_goals.goals.1.units"].unit == "external"  # no currency: never accepted as money
    assert all(f.derivation.endswith("not checked") for f in facts.values())


def account(balance: int) -> BankAccount:
    return BankAccount("acc_1", "0-000-00-12345-6", "CLP", balance)


def move(mid: str, day: int, amount: int) -> BankMovement:
    return BankMovement(mid, date(2026, 10, day), f"COMPRA {mid}", amount)


def test_first_sync_has_no_summary_and_stays_unverified() -> None:
    statement, state = statement_from_sync("fintoc", account(500_000), [move("m1", 1, -20_000), move("m2", 3, 100_000)], None, date(2026, 10, 5))
    assert statement is not None and statement.summary is None and statement.source == "api"
    assert [i.code for i in reconcile(statement).issues] == [IssueCode.NO_SUMMARY]
    assert state.balance == 500_000 and state.seen == ("m1", "m2")


def test_a_later_sync_reconciles_new_movements_against_both_balances() -> None:
    _, first = statement_from_sync("fintoc", account(500_000), [move("m1", 1, -20_000)], None, date(2026, 10, 5))
    moves = [move("m1", 1, -20_000), move("m3", 6, -30_000), move("m4", 7, 10_000)]
    statement, second = statement_from_sync("fintoc", account(480_000), moves, first, date(2026, 10, 8))
    assert statement is not None
    assert [line.description for line in statement.lines] == ["COMPRA m3", "COMPRA m4"]  # m1 was read before
    assert reconcile(statement).issues == ()
    assert second.seen == ("m1", "m3", "m4")


def test_a_balance_that_moved_without_movements_is_reported() -> None:
    _, first = statement_from_sync("fintoc", account(500_000), [move("m1", 1, -20_000)], None, date(2026, 10, 5))
    statement, _ = statement_from_sync("fintoc", account(450_000), [move("m1", 1, -20_000)], first, date(2026, 10, 8))
    assert statement is not None and statement.lines == ()
    assert [i.code for i in reconcile(statement).issues] == [IssueCode.CLOSING_BALANCE]


def test_nothing_new_is_no_statement() -> None:
    _, first = statement_from_sync("fintoc", account(500_000), [move("m1", 1, -20_000)], None, date(2026, 10, 5))
    statement, _ = statement_from_sync("fintoc", account(500_000), [move("m1", 1, -20_000)], first, date(2026, 10, 8))
    assert statement is None


def test_state_round_trips() -> None:
    _, state = statement_from_sync("fintoc", account(500_000), [move("m1", 1, -20_000)], None, date(2026, 10, 5))
    assert load_state(dump_state({"acc_1": state})) == {"acc_1": state}
    assert load_state(None) == {}
