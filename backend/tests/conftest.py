from __future__ import annotations

from pathlib import Path

import pytest

from neural_ledger.adapters.outbound.fixtures.persona_source import PersonaFixtureSource
from neural_ledger.bootstrap.config import Settings
from neural_ledger.bootstrap.container import build
from neural_ledger.domain.finance.params import FC_0_1

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "data"
CONTRACTS = REPO / "contracts"


def make_settings(**overrides) -> Settings:
    base = dict(
        clock="fixed",
        ids="sequential",
        data_dir=DATA,
        contracts_dir=CONTRACTS,
        hmac_secret="test-secret-at-least-16-chars",
    )
    base.update(overrides)
    return Settings(**base)


@pytest.fixture
def system():
    """(services, adapters) wired exactly like production, offline, deterministic."""
    return build(make_settings())


@pytest.fixture
def services(system):
    return system[0]


@pytest.fixture
def adapters(system):
    return system[1]


@pytest.fixture(scope="session")
def params():
    return FC_0_1


@pytest.fixture(scope="session")
def camila():
    return PersonaFixtureSource(DATA / "personas").load("camila")


@pytest.fixture(scope="session")
def diego():
    return PersonaFixtureSource(DATA / "personas").load("diego")
