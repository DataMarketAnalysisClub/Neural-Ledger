"""ADR-048 step 6: write/read parity. Every declaration the constructor accepts is one both stores accept, matches
contracts/memory/declaration.schema.json, and reads back from its stored record unchanged."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone

import pytest
from hypothesis import given
from hypothesis import strategies as st

from neural_ledger.domain.memory.catalog import (
    MAX_SALARY_NET,
    ChatOrigin,
    Declaration,
    ProfileOrigin,
    SalaryNet,
    Source,
    StatementOrigin,
    check_appended,
    declaration_record,
    parse_declaration,
)
from neural_ledger.domain.shared.month import Month

from .strategies import PROPERTY_SETTINGS

pytestmark = pytest.mark.property

ids = st.text(min_size=1, max_size=24)
origins = st.one_of(
    st.builds(ChatOrigin, ids, ids), st.just(ProfileOrigin()), st.builds(StatementOrigin, ids, ids),
)
zones = st.one_of(st.just(UTC), st.integers(-14 * 60, 14 * 60).map(lambda m: timezone(timedelta(minutes=m))))


@st.composite
def declarations(draw) -> Declaration:
    at = draw(st.datetimes(min_value=datetime(2000, 1, 1), max_value=datetime(2100, 1, 1), timezones=zones))
    return Declaration(
        memory_id=draw(ids), chain_id=draw(ids), version=draw(st.integers(1, 10_000)), user_id=draw(ids),
        value=SalaryNet(draw(st.integers(1, MAX_SALARY_NET)), Month(draw(st.integers(2000, 2100)), draw(st.integers(1, 12)))),
        confirmed_at=at, source=draw(st.sampled_from(Source)), origin=draw(origins), audit_ref=draw(ids),
    )


@PROPERTY_SETTINGS
@given(declarations())
def test_an_accepted_declaration_round_trips_and_matches_the_contract(declaration):
    pytest.importorskip("jsonschema")
    from tests.contract.test_contracts import validate

    record = json.loads(json.dumps(declaration_record(declaration)))
    validate(record, "memory/declaration.schema.json")
    assert parse_declaration(record, declaration.user_id) == declaration
    check_appended((declaration,), declaration.version - 1)  # and a store would take it
