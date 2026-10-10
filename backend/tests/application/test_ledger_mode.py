"""NL_MODEL_SOURCE=ledger: the app runs on the generated ledgers + stage-1 estimators and gives
the same answers as the calibrated fixtures (which stay the default and the golden reference).
Ledger envelopes also end with the estimator's facts and warnings (ADR-017, Proposed)."""

from __future__ import annotations

import pytest

from neural_ledger.adapters.inbound.cli.commands import run_demo
from neural_ledger.application.use_cases.financial import FinancialUseCases
from neural_ledger.bootstrap.config import Settings
from neural_ledger.bootstrap.container import build
from neural_ledger.domain.shared.serialization import to_primitive
from tests.conftest import make_settings


def test_fixture_stays_the_default_source():
    assert Settings().model_source == "fixture"
    assert Settings.from_env({}).model_source == "fixture"
    assert Settings.from_env({"NL_MODEL_SOURCE": "ledger"}).model_source == "ledger"


CALLS = (
    lambda f, user: f.forecast(user, 6, "conservative", "none"),
    lambda f, user: f.simulate_purchase(user, 400_000, 12, "2026-12"),
    lambda f, user: f.protected_surplus(user, 6, "recommended"),
    lambda f, user: f.capacity(user),
    lambda f, user: f.savings_plan(user),
)


def _without_evidence(services) -> FinancialUseCases:
    """The same ledger wiring without forwarding: what ledger mode returned before ADR-017."""
    f = services.financial
    return FinancialUseCases(f._source, f._snapshots, f._bank, f._profiles, f.params)


@pytest.mark.parametrize("user", ["camila", "diego"])
def test_ledger_mode_answers_like_fixture_mode(user):
    fixture, _ = build(make_settings())
    ledger, adapters = build(make_settings(model_source="ledger"))
    _, evidence = adapters.source.load_with_evidence(user)
    plain = _without_evidence(ledger)
    for call in CALLS:
        a, b, before = call(fixture.financial, user), call(ledger.financial, user), call(plain, user)
        assert a.status is b.status
        assert to_primitive(a.data) == to_primitive(b.data)
        # same money facts as the fixtures, then exactly the estimator's facts and warnings
        assert b.facts[: len(a.facts)] == a.facts
        assert b.warnings[: len(a.warnings)] == a.warnings
        tail = b.facts[len(a.facts):]
        assert [(f.key, f.value, f.unit) for f in tail] == [(f.key, f.value, f.unit) for f in evidence.facts]
        assert all(f.key.startswith("estimate.") and "; source=ledger-estimator; " in f.derivation for f in tail)
        assert b.warnings[len(a.warnings):] == evidence.warnings
        # forwarding changes no number and no snapshot id of the ledger answer
        assert b.snapshot_id == before.snapshot_id
        assert to_primitive(b.data) == to_primitive(before.data)
        assert b.facts[: len(before.facts)] == before.facts and b.warnings[: len(before.warnings)] == before.warnings
        assert a.snapshot_id != b.snapshot_id  # the snapshot id names its source


def test_demo_arc_runs_on_the_ledger(capsys):
    services, _ = build(make_settings(model_source="ledger"))
    assert run_demo(services) == 0
    out = capsys.readouterr().out
    assert "20,000 CLP" in out and "100,000 CLP" in out and "Audit chain: OK" in out


def test_unknown_model_source_is_rejected():
    with pytest.raises(ValueError):
        build(make_settings(model_source="mongo"))
