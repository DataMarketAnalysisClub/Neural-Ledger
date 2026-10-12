"""contracts/ledger/ledger.schema.json and the estimator's input limits never drift apart."""

from __future__ import annotations

import json

import pytest

from neural_ledger.domain.finance.estimation import MAX_ABS_AMOUNT, SUPPORTED_CURRENCIES
from neural_ledger.domain.ledger.entities import AccountType, IncomeType, TransactionKind

from ..conftest import CONTRACTS, LEDGERS

jsonschema = pytest.importorskip("jsonschema")
SCHEMA = json.loads((CONTRACTS / "ledger" / "ledger.schema.json").read_text(encoding="utf-8"))
PROPS = SCHEMA["properties"]
TXN = PROPS["transactions"]["items"]["properties"]
ACCOUNT = PROPS["accounts"]["items"]["properties"]


def test_limits_match_the_estimator_constants():
    assert set(PROPS["currency"]["enum"]) == set(SUPPORTED_CURRENCIES) == set(ACCOUNT["currency"]["enum"])
    amount = SCHEMA["$defs"]["amount"]
    assert (amount["minimum"], amount["maximum"]) == (-MAX_ABS_AMOUNT, MAX_ABS_AMOUNT)
    bounded = [
        PROPS["income_profile"]["properties"]["contracted_net"],
        PROPS["buckets"]["items"]["properties"]["amount"],
        PROPS["goals"]["items"]["properties"]["target_amount"],
        PROPS["goals"]["items"]["properties"]["saved_amount"],
    ]
    assert all(b["maximum"] == MAX_ABS_AMOUNT for b in bounded)


def test_enums_match_the_domain():
    assert set(TXN["kind"]["enum"]) == {k.value for k in TransactionKind}
    assert set(ACCOUNT["type"]["enum"]) == {t.value for t in AccountType}
    assert set(PROPS["income_profile"]["properties"]["type"]["enum"]) == {t.value for t in IncomeType}


@pytest.mark.parametrize("user", ["camila", "diego"])
def test_generated_ledgers_satisfy_the_contract(user):
    ledger = json.loads((LEDGERS / f"{user}.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(SCHEMA, format_checker=jsonschema.FormatChecker()).validate(ledger)
