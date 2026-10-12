"""Every sandbox account reconciles: opening balance + sum of its transactions = closing balance.

Duplicated txn_ids are an import artifact (the same movement listed twice), so each txn_id is
counted once, exactly as the estimators do. Own-account transfers (`transfer_own`) must
balance across accounts; see docs/DECISIONS.md ADR-012 for why the estimators trust them.
"""

from __future__ import annotations

import json

import pytest

from tests.conftest import LEDGERS

pytestmark = pytest.mark.golden


def _ledger(user: str) -> dict:
    return json.loads((LEDGERS / f"{user}.json").read_text(encoding="utf-8"))


def _unique(transactions: list[dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    for t in transactions:
        seen.setdefault(t["txn_id"], t)
    return list(seen.values())


@pytest.mark.parametrize("user", ["camila", "diego"])
@pytest.mark.parametrize("account", ["checking", "credit_card", "savings"])
def test_account_reconciles(user, account):
    ledger = _ledger(user)
    [acc] = [a for a in ledger["accounts"] if a["account_id"] == account]
    movements = sum(t["amount"] for t in _unique(ledger["transactions"]) if t["account_id"] == account)
    assert acc["opening_balance"] + movements == acc["balance"]


@pytest.mark.parametrize("user", ["camila", "diego"])
def test_savings_buckets_add_up_to_the_savings_balance(user):
    ledger = _ledger(user)
    [savings] = [a for a in ledger["accounts"] if a["type"] == "savings"]
    assert sum(b["amount"] for b in ledger["buckets"]) == savings["balance"]


@pytest.mark.parametrize("user", ["camila", "diego"])
def test_card_payments_leave_checking_and_reach_the_card(user):
    """The card payment appears twice (checking out, card in) and nets to zero across the sandbox."""
    unique = _unique(_ledger(user)["transactions"])
    out_of_checking = -sum(t["amount"] for t in unique if t["account_id"] == "checking" and t["category"] == "card_payment")
    into_card = sum(t["amount"] for t in unique if t["account_id"] == "credit_card" and t["kind"] == "card_payment")
    assert out_of_checking == into_card > 0
