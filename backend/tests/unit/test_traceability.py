"""Snapshot ids come from the ledger CONTENT and the parameter version, not from labels."""

from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal

import pytest

from neural_ledger.adapters.outbound.bank.simulated import SimulatedSandboxBank
from neural_ledger.adapters.outbound.fixtures.ledger_source import parse_ledger
from neural_ledger.adapters.outbound.persistence.memory import InMemorySnapshotStore, InMemoryUserProfileStore
from neural_ledger.application.use_cases.financial import FinancialUseCases
from neural_ledger.domain.finance.estimation import estimate_model
from tests.conftest import LEDGERS


@pytest.fixture(scope="module")
def raw():
    return json.loads((LEDGERS / "camila.json").read_text(encoding="utf-8"))


def _estimate(raw_ledger, params):
    return estimate_model(parse_ledger(raw_ledger), params)


class _Source:
    def __init__(self, model) -> None:
        self._model = model

    def load(self, user_id):
        return self._model


def _forecast_id(model, params) -> str:
    uc = FinancialUseCases(_Source(model), InMemorySnapshotStore(), SimulatedSandboxBank(), InMemoryUserProfileStore([]), params)
    return uc.forecast("camila").snapshot_id


def _mutated(raw_ledger, **changes):
    copy = json.loads(json.dumps(raw_ledger))
    for key, value in changes.items():
        copy[key] = value
    return copy


def test_one_peso_changes_the_snapshot_id(raw, params):
    base = _estimate(raw, params)
    changed = json.loads(json.dumps(raw))
    target = next(t for t in changed["transactions"] if t["category"] == "groceries")
    target["amount"] -= 1
    other = _estimate(changed, params)
    assert base.data.source_version != other.data.source_version
    assert base.snapshot_id != other.snapshot_id
    assert _forecast_id(base.data, params) != _forecast_id(other.data, params)


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda r: r["accounts"][0].update(balance=r["accounts"][0]["balance"] + 1), id="account balance"),
        pytest.param(lambda r: r["buckets"][0].update(amount=r["buckets"][0]["amount"] + 1), id="savings bucket"),
        pytest.param(lambda r: r["goals"][0].update(target_amount=r["goals"][0]["target_amount"] + 1), id="goal"),
        pytest.param(lambda r: r["income_profile"].update(contracted_net=r["income_profile"]["contracted_net"] + 1), id="income profile"),
        pytest.param(lambda r: r["transactions"][0].update(merchant_raw=r["transactions"][0]["merchant_raw"] + " X"), id="merchant text"),
    ],
)
def test_the_digest_covers_the_whole_input(raw, params, mutate):
    changed = json.loads(json.dumps(raw))
    mutate(changed)
    assert parse_ledger(changed) != parse_ledger(raw)
    assert _estimate(changed, params).data.source_version != _estimate(raw, params).data.source_version


def test_the_digest_keeps_card_rates_exact(raw, params):
    snapshot = parse_ledger(raw)
    i, line = next((i, t) for i, t in enumerate(snapshot.transactions) if t.installment and t.installment.monthly_rate)
    nudged = replace(line, installment=replace(line.installment, monthly_rate=line.installment.monthly_rate + Decimal("1e-9")))
    other = replace(snapshot, transactions=snapshot.transactions[:i] + (nudged,) + snapshot.transactions[i + 1 :])
    assert estimate_model(other, params).data.source_version != estimate_model(snapshot, params).data.source_version


def test_order_labels_and_duplicates_do_not_change_the_snapshot_id(raw, params):
    base = _estimate(raw, params)
    reordered = _mutated(raw, transactions=list(reversed(raw["transactions"])), ledger_version="another-label")
    assert _estimate(reordered, params).snapshot_id == base.snapshot_id
    duplicated = _mutated(raw, transactions=raw["transactions"] + [raw["transactions"][5]])
    assert _estimate(duplicated, params).snapshot_id == base.snapshot_id


def test_snapshot_ids_include_the_params_version(raw, params):
    bumped = replace(params, version="fc-test")
    a, b = _estimate(raw, params), _estimate(raw, bumped)
    assert a.data == b.data  # same numbers...
    assert a.snapshot_id != b.snapshot_id  # ...but a different snapshot
    assert _forecast_id(a.data, params) != _forecast_id(a.data, bumped)
