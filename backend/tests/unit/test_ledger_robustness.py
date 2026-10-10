"""Malformed ledgers never raise an uncaught exception: INVALID_INPUT names the field.

Each case is checked twice: at the adapter + estimator (parse_ledger, estimate_model) and
through the whole read path (LedgerModelSource -> FinancialUseCases), which must answer an
envelope, never a traceback. A hypothesis fuzz mutates random fields with random JSON values.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable

import pytest
from hypothesis import given
from hypothesis import strategies as st

from neural_ledger.adapters.outbound.bank.simulated import SimulatedSandboxBank
from neural_ledger.adapters.outbound.fixtures.ledger_source import LedgerModelSource, parse_ledger
from neural_ledger.adapters.outbound.persistence.memory import InMemorySnapshotStore, InMemoryUserProfileStore
from neural_ledger.application.use_cases.financial import FinancialUseCases
from neural_ledger.domain.finance.estimation import MAX_ABS_AMOUNT, estimate_model
from neural_ledger.domain.finance.params import FC_0_1
from neural_ledger.domain.shared.envelope import Status
from neural_ledger.domain.shared.errors import InvalidInput
from tests.conftest import LEDGERS
from tests.property.strategies import PROPERTY_SETTINGS

RAW = json.loads((LEDGERS / "camila.json").read_text(encoding="utf-8"))


def _first(raw: dict, predicate: Callable[[dict], bool]) -> int:
    return next(i for i, t in enumerate(raw["transactions"]) if predicate(t))


def _txn(raw, predicate, **changes) -> str:
    i = _first(raw, predicate)
    raw["transactions"][i].update(changes)
    return f"transactions[{i}]"


def _drop(raw, key) -> str:
    i = _first(raw, lambda t: t["kind"] == "purchase")
    del raw["transactions"][i][key]
    return f"transactions[{i}].{key}"


def _conflicting_duplicate(raw) -> str:
    original = next(t for t in raw["transactions"] if t["category"] == "groceries")
    raw["transactions"].append({**original, "amount": original["amount"] - 1})
    return f"transactions[{len(raw['transactions']) - 1}].txn_id"


PURCHASE = lambda t: t["kind"] == "purchase"  # noqa: E731
SALARY = lambda t: t["kind"] == "income"  # noqa: E731
CUOTA = lambda t: t["installment"] is not None  # noqa: E731

CASES = {
    "non-integer amount": lambda r: _txn(r, PURCHASE, amount=-1234.5) + ".amount",
    "amount as text": lambda r: _txn(r, PURCHASE, amount="-1000") + ".amount",
    "absurd amount": lambda r: _txn(r, PURCHASE, amount=-(MAX_ABS_AMOUNT + 1)) + ".amount",
    "ledger currency is not CLP": lambda r: (r.update(currency="USD"), "currency")[1],
    "account in another currency": lambda r: (r["accounts"][2].update(currency="USD"), "accounts[2].currency")[1],
    "absurd account balance": lambda r: (r["accounts"][0].update(balance=10**12), "accounts[0].balance")[1],
    "date after as_of": lambda r: _txn(r, PURCHASE, date="2026-10-30") + ".date",
    "impossible date": lambda r: _txn(r, PURCHASE, date="2026-13-01") + ".date",
    "unknown kind": lambda r: _txn(r, PURCHASE, kind="teleport") + ".kind",
    "negative income": lambda r: _txn(r, SALARY, amount=-1_800_000) + ".amount",
    "zero income": lambda r: _txn(r, SALARY, amount=0) + ".amount",
    "unknown account": lambda r: _txn(r, PURCHASE, account_id="brokerage") + ".account_id",
    "missing date": lambda r: _drop(r, "date"),
    "missing amount": lambda r: _drop(r, "amount"),
    "txn_id reused with other content": _conflicting_duplicate,
    "cuota number above its total": lambda r: _txn(r, CUOTA, installment={**next(t for t in r["transactions"] if CUOTA(t))["installment"], "installment_number": 99}) + ".installment",
    "as_of mid-cycle": lambda r: (r.update(as_of="2026-10-15"), "as_of")[1],
    "negative contracted salary": lambda r: (r["income_profile"].update(contracted_net=-5), "income_profile.contracted_net")[1],
    "transactions is not a list": lambda r: (r.update(transactions={"a": 1}), "transactions")[1],
}


def evaluate(raw) -> tuple[Status, str | None]:
    try:
        snapshot = parse_ledger(raw)
    except InvalidInput as exc:
        return Status.INVALID_INPUT, exc.field
    envelope = estimate_model(snapshot, FC_0_1)
    return envelope.status, envelope.field


def _use_cases(tmp_path, raw) -> FinancialUseCases:
    (tmp_path / "camila.json").write_text(json.dumps(raw), encoding="utf-8")
    source = LedgerModelSource(tmp_path, FC_0_1)
    return FinancialUseCases(source, InMemorySnapshotStore(), SimulatedSandboxBank(), InMemoryUserProfileStore([]), FC_0_1)


def test_the_untouched_ledger_is_valid():
    assert evaluate(copy.deepcopy(RAW)) == (Status.OK, None)


@pytest.mark.parametrize("case", list(CASES), ids=list(CASES))
def test_malformed_ledger_is_invalid_input_with_the_field(case):
    raw = copy.deepcopy(RAW)
    field = CASES[case](raw)
    assert evaluate(raw) == (Status.INVALID_INPUT, field)


@pytest.mark.parametrize("case", list(CASES), ids=list(CASES))
def test_malformed_ledger_through_the_use_cases(case, tmp_path):
    raw = copy.deepcopy(RAW)
    field = CASES[case](raw)
    envelope = _use_cases(tmp_path, raw).forecast("camila")
    assert (envelope.status, envelope.field) == (Status.INVALID_INPUT, field)


def test_a_file_that_is_not_json_is_invalid_input(tmp_path):
    (tmp_path / "camila.json").write_text("{not json", encoding="utf-8")
    uc = FinancialUseCases(LedgerModelSource(tmp_path, FC_0_1), InMemorySnapshotStore(), SimulatedSandboxBank(), InMemoryUserProfileStore([]), FC_0_1)
    envelope = uc.capacity("camila")
    assert (envelope.status, envelope.field) == (Status.INVALID_INPUT, "ledger")


def test_exact_duplicates_are_not_an_error():
    raw = copy.deepcopy(RAW)
    raw["transactions"].append(copy.deepcopy(raw["transactions"][7]))
    assert evaluate(raw) == (Status.OK, None)


json_values = st.recursive(
    st.none() | st.booleans() | st.integers(-(10**15), 10**15) | st.floats(allow_nan=True) | st.text(max_size=12),
    lambda children: st.lists(children, max_size=3) | st.dictionaries(st.text(max_size=6), children, max_size=3),
    max_leaves=5,
)
TXN_KEYS = ["txn_id", "account_id", "date", "amount", "merchant_raw", "category", "kind", "installment"]
TOP_KEYS = ["user_id", "currency", "as_of", "income_profile", "accounts", "buckets", "goals", "transactions"]


@PROPERTY_SETTINGS
@given(st.data())
def test_fuzzed_ledgers_never_raise(data):
    raw = copy.deepcopy(RAW)
    if data.draw(st.booleans()):
        txn = raw["transactions"][data.draw(st.integers(0, len(raw["transactions"]) - 1))]
        txn[data.draw(st.sampled_from(TXN_KEYS))] = data.draw(json_values)
    else:
        raw[data.draw(st.sampled_from(TOP_KEYS))] = data.draw(json_values)
    status, field = evaluate(raw)
    assert status in (Status.OK, Status.INVALID_INPUT, Status.INSUFFICIENT_DATA)
    if status is Status.INVALID_INPUT:
        assert field
