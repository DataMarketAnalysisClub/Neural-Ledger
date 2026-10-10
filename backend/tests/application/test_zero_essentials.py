"""Capacity with zero monthly essentials is unknown (H4), not a crash: every path that reaches
assess_capacity must answer INSUFFICIENT_DATA instead of raising ZeroDivisionError."""

from __future__ import annotations

import json
import shutil
from dataclasses import replace

import pytest

from neural_ledger.adapters.outbound.bank.simulated import SimulatedSandboxBank
from neural_ledger.adapters.outbound.persistence.memory import InMemorySnapshotStore, InMemoryUserProfileStore
from neural_ledger.application.use_cases.financial import FinancialUseCases
from neural_ledger.bootstrap.container import build
from neural_ledger.domain.finance.capacity import assess_capacity
from neural_ledger.domain.finance.model import CommitmentType
from neural_ledger.domain.shared.envelope import Status
from neural_ledger.domain.shared.errors import InsufficientData
from tests.conftest import CONTRACTS, DATA, make_settings

MISSING = ("spend.essentials",)


@pytest.fixture(scope="module")
def no_essentials(camila):
    return replace(
        camila,
        user_id="zero",
        commitments=tuple(c for c in camila.commitments if c.type is CommitmentType.SUBSCRIPTION),
        spend=replace(camila.spend, categories=tuple(replace(c, essential=False) for c in camila.spend.categories)),
    )


class _Source:
    def __init__(self, model) -> None:
        self._model = model

    def load(self, user_id: str):
        return self._model


@pytest.fixture
def financial(no_essentials, params):
    return FinancialUseCases(_Source(no_essentials), InMemorySnapshotStore(), SimulatedSandboxBank(), InMemoryUserProfileStore([]), params)


def test_engine_raises_insufficient_data_instead_of_dividing_by_zero(no_essentials, params):
    with pytest.raises(InsufficientData) as exc:
        assess_capacity(no_essentials, params)
    assert exc.value.missing == MISSING


@pytest.mark.parametrize(
    "call",
    [
        pytest.param(lambda f: f.capacity("zero"), id="capacity"),
        pytest.param(lambda f: f.permitted_profile("zero", "aggressive"), id="permitted_profile"),
        pytest.param(lambda f: f.savings_plan("zero"), id="savings_plan"),
        pytest.param(lambda f: f.forecast("zero", 6, "conservative", "recommended"), id="forecast_with_recommended_plan"),
        pytest.param(lambda f: f.protected_surplus("zero", 6, "recommended"), id="surplus_with_recommended_plan"),
        pytest.param(lambda f: f.simulate_purchase("zero", 400_000, 12, "2026-12", None, "recommended"), id="purchase_with_recommended_plan"),
    ],
)
def test_every_use_case_path_answers_insufficient_data(financial, call):
    envelope = call(financial)
    assert envelope.status is Status.INSUFFICIENT_DATA
    assert envelope.missing == MISSING


def test_paths_that_do_not_need_capacity_still_answer(financial):
    assert financial.forecast("zero", 6, "conservative", "none").ok
    assert financial.protected_surplus("zero", 6, "none").ok


def test_chat_and_narrator_answer_without_crashing(tmp_path):
    personas = tmp_path / "personas"
    shutil.copytree(DATA / "personas", personas)
    raw = json.loads((DATA / "personas" / "camila.json").read_text(encoding="utf-8"))
    raw["user_id"] = "zero"
    raw["commitments"] = [c for c in raw["commitments"] if c["type"] == "subscription"]
    for c in raw["spend"]["categories"]:
        c["essential"] = False
    (personas / "zero.json").write_text(json.dumps(raw), encoding="utf-8")
    services, _ = build(make_settings(data_dir=tmp_path, contracts_dir=CONTRACTS))

    reply = services.chat.handle("zero-session", "zero", "Help me save for my trip.")
    assert "derive_permitted_profile" in reply.tools_called
    assert "enough data" in reply.text
    assert reply.verification is not None and reply.verification.ok
    assert reply.pending_proposal is None
    assert services.audit.verify().ok
