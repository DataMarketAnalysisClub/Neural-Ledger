"""Golden answers E01-E14 run twice: on the calibrated fixtures and on the models the stage-1
estimators produce from the generated ledgers. Both must give exactly the same numbers."""

from __future__ import annotations

import pytest

from neural_ledger.adapters.outbound.fixtures.persona_source import PersonaFixtureSource
from tests.conftest import DATA


def _model(source: str, user: str, ledger_source):
    if source == "ledger":
        return ledger_source.load(user)
    return PersonaFixtureSource(DATA / "personas").load(user)


@pytest.fixture(scope="session", params=["fixture", "ledger"])
def camila(request, ledger_source):
    return _model(request.param, "camila", ledger_source)


@pytest.fixture(scope="session", params=["fixture", "ledger"])
def diego(request, ledger_source):
    return _model(request.param, "diego", ledger_source)
