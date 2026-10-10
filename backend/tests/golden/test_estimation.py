"""Acceptance test for Role A's estimators + Role E's generator (stage 1).

When data/ledgers/camila.json exists and estimate_model() is implemented, this must pass and
the xfail marker must be removed (xfail_strict makes an unexpected pass fail the suite).
"""

from __future__ import annotations

import pytest

from neural_ledger.domain.finance.estimation import estimate_model
from neural_ledger.domain.finance.forecast import Scenario, project


@pytest.mark.xfail(reason="Role E generator + Role A estimators not implemented yet", raises=(NotImplementedError, FileNotFoundError))
def test_estimators_reproduce_camila_calibration(camila, params):
    from pathlib import Path

    ledger_file = Path(__file__).resolve().parents[3] / "data" / "ledgers" / "camila.json"
    if not ledger_file.exists():
        raise FileNotFoundError(ledger_file)
    snapshot = ...  # TODO(Role C/E): load the generated ledger into a LedgerSnapshot
    envelope = estimate_model(snapshot, params)
    estimated = envelope.data
    assert project(estimated, params, Scenario.CONSERVATIVE, 6) == project(camila, params, Scenario.CONSERVATIVE, 6)
