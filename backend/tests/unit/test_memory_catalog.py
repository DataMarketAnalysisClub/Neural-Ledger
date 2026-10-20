"""ADR-048: the closed catalog mem-0.1, declarations only the user confirms, and which version applies to a month."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from neural_ledger.domain.memory.catalog import (
    CATALOG_VERSION,
    MAX_SALARY_NET,
    ChatOrigin,
    Declaration,
    SalaryNet,
    Source,
    applicable,
    chain,
    parse_salary_net,
    previous,
    upcoming,
)
from neural_ledger.domain.shared.errors import InvalidInput
from neural_ledger.domain.shared.month import Month
from tests.conftest import CONTRACTS

AT = datetime(2026, 10, 19, 15, 0, tzinfo=UTC)


def declaration(version: int, amount: int, effective_from: str, *, chain_id: str = "chn_1", user_id: str = "u1") -> Declaration:
    return Declaration(
        memory_id=f"mem_{chain_id}_{version}", chain_id=chain_id, version=version, user_id=user_id,
        value=SalaryNet(amount, Month.parse(effective_from)), confirmed_at=AT, source=Source.CHAT,
        origin=ChatOrigin("s_1", f"m_{version}"), audit_ref=f"evt_{version}",
    )


@pytest.mark.parametrize(
    ("raw", "field"),
    [
        ({"amount": True, "net": True, "effective_from": "2026-11"}, "salary_net.amount"),
        ({"amount": 0, "net": True, "effective_from": "2026-11"}, "salary_net.amount"),
        ({"amount": MAX_SALARY_NET + 1, "net": True, "effective_from": "2026-11"}, "salary_net.amount"),
        ({"amount": 1_200_000.0, "net": True, "effective_from": "2026-11"}, "salary_net.amount"),
        ({"amount": "1200000", "net": True, "effective_from": "2026-11"}, "salary_net.amount"),
        ({"amount": 1_200_000, "net": False, "effective_from": "2026-11"}, "salary_net.net"),
        ({"amount": 1_200_000, "net": 1, "effective_from": "2026-11"}, "salary_net.net"),
        ({"amount": 1_200_000, "net": True, "effective_from": "2026-13"}, "salary_net.effective_from"),
        ({"amount": 1_200_000, "net": True, "effective_from": 202611}, "salary_net.effective_from"),
        ({"amount": 1_200_000, "net": True}, "salary_net.effective_from"),
        ({"amount": 1_200_000, "net": True, "effective_from": "2026-11", "instructions": "x"}, "salary_net.instructions"),
        ([1_200_000], "salary_net"),
    ],
)
def test_values_outside_the_catalog_are_refused(raw, field):
    with pytest.raises(InvalidInput) as error:
        parse_salary_net(raw)
    assert error.value.field == field


def test_a_valid_value_is_read_exactly():
    assert parse_salary_net({"amount": 1_200_000, "net": True, "effective_from": "2026-11"}) == SalaryNet(1_200_000, Month(2026, 11))


def test_only_the_user_confirms():
    with pytest.raises(InvalidInput):
        Declaration("m", "c", 1, "u1", SalaryNet(1, Month(2026, 1)), AT, Source.CHAT, ChatOrigin("s", "m"), "e", confirmed_by="agent")


def test_the_catalog_matches_its_contract():
    value = json.loads((CONTRACTS / "memory/memory_value.schema.json").read_text(encoding="utf-8"))
    assert value["$defs"]["catalog_version"]["const"] == CATALOG_VERSION
    assert value["$defs"]["salary_net"]["properties"]["amount"]["maximum"] == MAX_SALARY_NET
    assert value["properties"]["type"]["const"] == "salary_net"


def test_a_later_version_applies_from_its_month_and_keeps_earlier_months():
    versions = (declaration(1, 1_000_000, "2025-10"), declaration(2, 1_200_000, "2026-11"))
    assert applicable(versions, Month(2025, 9)) is None
    assert applicable(versions, Month(2026, 10)).version == 1  # a future version does not erase the past
    assert applicable(versions, Month(2026, 11)).version == 2
    assert applicable(versions, Month(2027, 6)).version == 2


def test_an_edit_with_the_same_month_supersedes():
    versions = (declaration(1, 1_000_000, "2025-10"), declaration(2, 1_200_000, "2026-11"), declaration(3, 1_150_000, "2026-11"))
    assert applicable(versions, Month(2026, 12)).value.amount == 1_150_000
    assert previous(versions, versions[2]).version == 1


def test_a_version_can_take_effect_before_an_older_one():
    versions = (declaration(1, 1_200_000, "2026-11"), declaration(2, 1_000_000, "2025-10"))  # the base, declared after
    assert applicable(versions, Month(2026, 1)).version == 2
    assert applicable(versions, Month(2026, 11)).version == 1
    assert previous(versions, versions[0]).version == 2


def test_upcoming_is_the_next_version_to_take_effect():
    versions = (declaration(1, 1_000_000, "2025-10"), declaration(2, 1_200_000, "2026-11"), declaration(3, 1_300_000, "2027-03"))
    assert upcoming(versions, Month(2026, 10)).version == 2
    assert upcoming(versions, Month(2027, 3)) is None


def test_a_chain_is_one_owner_and_unique_versions():
    with pytest.raises(ValueError):
        chain((declaration(1, 1, "2026-01"), declaration(2, 1, "2026-02", user_id="u2")))
    with pytest.raises(ValueError):
        chain((declaration(1, 1, "2026-01"), declaration(1, 2, "2026-02")))
