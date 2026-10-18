"""ADR-029 step 2: an account's financial model comes from its own imported statements.

Personas keep their fixtures (E01-E14 stay as they are); any other user gets the model the stage-1 estimators
build from their verified statements, or an INSUFFICIENT_DATA envelope saying what is missing.
"""

from __future__ import annotations

from datetime import date

import pytest

from neural_ledger.adapters.outbound.statements.synthetic import SyntheticStatements
from neural_ledger.bootstrap.container import build
from neural_ledger.domain.finance.paycycle import is_eve_of_payday
from neural_ledger.domain.shared.envelope import Status
from tests.conftest import make_settings

ACCOUNT = "usr_statements"


def _imported(months: int, user: str = ACCOUNT, seed: int = 4):
    services, _ = build(make_settings())
    for sample in SyntheticStatements().checking(seed, date(2026, 9, 30), months=months):
        assert services.statements.import_statement(user, sample.content).ok
    return services


def test_seven_months_of_statements_give_an_account_its_own_forecast():
    services = _imported(7)  # March to September: six full pay cycles, April to September
    forecast = services.financial.forecast(ACCOUNT)
    assert forecast.status is Status.OK
    assert forecast.as_of == "2026-09-29" and is_eve_of_payday(date.fromisoformat(forecast.as_of))
    for envelope in (services.financial.financial_state(ACCOUNT), services.financial.protected_surplus(ACCOUNT),
                     services.financial.capacity(ACCOUNT), services.financial.simulate_purchase(ACCOUNT, 200_000, 3)):
        assert envelope.status is Status.OK, (envelope.missing, envelope.message)


def test_the_model_is_estimated_from_the_accounts_own_lines():
    services = _imported(7)
    state = services.financial.financial_state(ACCOUNT)
    facts = {f.key: f.value for f in state.facts}
    persona = {f.key: f.value for f in services.financial.financial_state("camila").facts}
    assert facts != persona  # not a persona's numbers
    assert services.financial.forecast(ACCOUNT).snapshot_id != services.financial.forecast(ACCOUNT, scenario="typical").snapshot_id


def test_six_calendar_months_are_five_full_cycles_and_say_so():
    services = _imported(6)  # April to September: April's cycle started on March 31, before the first statement
    forecast = services.financial.forecast(ACCOUNT)
    assert forecast.status is Status.INSUFFICIENT_DATA
    assert any("at least 6" in m and "found 5" in m for m in forecast.missing), forecast.missing


def test_an_account_with_no_statements_is_told_to_import_them():
    services, _ = build(make_settings())
    forecast = services.financial.forecast(ACCOUNT)
    assert forecast.status is Status.INSUFFICIENT_DATA and forecast.missing == ("statements",)


def test_one_accounts_statements_never_feed_anothers_model():
    services = _imported(7)
    assert services.financial.forecast("usr_someone_else").missing == ("statements",)  # C04
    assert services.financial.forecast(ACCOUNT).status is Status.OK


@pytest.mark.parametrize("persona", ["camila", "diego"])
def test_personas_keep_their_fixtures_even_if_they_import_statements(persona):
    before = build(make_settings())[0].financial.forecast(persona)
    services = _imported(7, user=persona)
    after = services.financial.forecast(persona)
    assert (after.status, after.snapshot_id, after.as_of) == (before.status, before.snapshot_id, before.as_of)
