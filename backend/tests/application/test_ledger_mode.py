"""NL_MODEL_SOURCE=ledger: the app runs on the generated ledgers + stage-1 estimators and gives
the same answers as the calibrated fixtures (which stay the default and the golden reference)."""

from __future__ import annotations

import pytest

from neural_ledger.adapters.inbound.cli.commands import run_demo
from neural_ledger.bootstrap.config import Settings
from neural_ledger.bootstrap.container import build
from neural_ledger.domain.shared.serialization import to_primitive
from tests.conftest import make_settings


def test_fixture_stays_the_default_source():
    assert Settings().model_source == "fixture"
    assert Settings.from_env({}).model_source == "fixture"
    assert Settings.from_env({"NL_MODEL_SOURCE": "ledger"}).model_source == "ledger"


@pytest.mark.parametrize("user", ["camila", "diego"])
def test_ledger_mode_answers_like_fixture_mode(user):
    fixture, _ = build(make_settings())
    ledger, _ = build(make_settings(model_source="ledger"))
    for call in (
        lambda s: s.financial.forecast(user, 6, "conservative", "none"),
        lambda s: s.financial.simulate_purchase(user, 400_000, 12, "2026-12"),
        lambda s: s.financial.protected_surplus(user, 6, "recommended"),
        lambda s: s.financial.capacity(user),
        lambda s: s.financial.savings_plan(user),
    ):
        a, b = call(fixture), call(ledger)
        assert a.status is b.status
        assert to_primitive(a.data) == to_primitive(b.data)
        assert a.facts == b.facts
        assert a.snapshot_id != b.snapshot_id  # the snapshot id names its source


def test_demo_arc_runs_on_the_ledger(capsys):
    services, _ = build(make_settings(model_source="ledger"))
    assert run_demo(services) == 0
    out = capsys.readouterr().out
    assert "20,000 CLP" in out and "100,000 CLP" in out and "Audit chain: OK" in out


def test_unknown_model_source_is_rejected():
    with pytest.raises(ValueError):
        build(make_settings(model_source="mongo"))
