"""Synthetic cartolas (`neural-ledger cartola` / `seed`): they read, reconcile and post like a real export."""

from __future__ import annotations

import random
from datetime import date

import pytest

from neural_ledger.adapters.inbound.cli.commands import main as cli
from neural_ledger.adapters.outbound.statements.banks.bice_xlsx import BiceTarjetaMovimientos
from neural_ledger.adapters.outbound.statements.banks.santander_xlsx import SantanderCuentaCorrienteXlsx
from neural_ledger.adapters.outbound.statements.reader import StatementFileReader
from neural_ledger.adapters.outbound.statements.synthetic import (
    HOLDER,
    HOLDER_EMAIL,
    HOLDER_RUT,
    Household,
    SyntheticStatements,
    card_export,
    checking_history,
)
from neural_ledger.bootstrap.container import build
from neural_ledger.domain.statements.model import reconcile
from tests.conftest import make_settings

SEEDS = range(25)


def _read(content: bytes):
    (statement,) = StatementFileReader().read(content)
    return statement


def test_same_seed_same_bytes_and_another_seed_differs():
    samples = SyntheticStatements()
    first = samples.checking(7, date(2026, 9, 1), months=2)
    assert [f.content for f in first] == [f.content for f in samples.checking(7, date(2026, 9, 1), months=2)]
    assert first[0].content != samples.checking(8, date(2026, 9, 1), months=2)[0].content
    assert samples.card(7, date(2026, 10, 1), date(2026, 10, 15)).content == samples.card(7, date(2026, 10, 1), date(2026, 10, 15)).content


@pytest.mark.parametrize("seed", SEEDS)
def test_checking_history_reconciles_chains_and_never_overdraws(seed):
    rng = random.Random(seed)
    history = checking_history(rng, Household.random(rng), date(2026, 3, 1), months=3, opening=50_000)  # low opening: the guard must act
    assert [c.month for c in history] == [date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 1)]
    for previous, cartola in zip(history, history[1:]):
        assert cartola.opening == previous.closing
    for cartola in history:
        statement = _read(cartola.content)
        assert statement.bank == SantanderCuentaCorrienteXlsx.code
        assert reconcile(statement).ok, reconcile(statement).issues
        assert len(statement.lines) == cartola.movements
        assert statement.summary.closing_balance == cartola.closing
        assert all(b.balance >= 0 for b in statement.daily_balances)
        assert all(statement.period_start <= line.posted_on <= statement.period_end for line in statement.lines)


@pytest.mark.parametrize("seed", SEEDS)
def test_card_export_is_a_reconciling_provisional_bice_export(seed):
    export = card_export(random.Random(seed), date(2026, 9, 23), date(2026, 10, 14))
    statement = _read(export.content)
    assert statement.bank == BiceTarjetaMovimientos.code and statement.provisional
    assert reconcile(statement).ok, reconcile(statement).issues
    assert len(statement.lines) == export.movements
    assert all(date(2026, 9, 23) <= line.posted_on <= date(2026, 10, 14) for line in statement.lines)


def test_import_verifies_posts_and_keeps_fictional_holder_out_of_the_store():
    services, _ = build(make_settings())
    for f in SyntheticStatements().checking(3, date(2026, 9, 1), months=2):
        result = services.statements.import_statement("camila", f.content)
        (imported,) = result.data.imports
        assert imported.statement.verified and imported.ledger.posted == imported.statement.line_count
    stored = str(services.statements.list_statements("camila").data) + str(services.ledger.list_transactions("camila").data)
    for value in (HOLDER, HOLDER_RUT, HOLDER_EMAIL):
        assert value not in stored


def test_savings_and_cash_lines_are_not_given_a_spending_category():
    """'Transf a Cuenta Ahorro' once came back as groceries at 0.50: savings must never count as spending in a category.

    Since ADR-024's checking rules the layout marks a savings transfer as the holder's own money, and since ADR-036 as
    Ahorro: `savings` by rule. A cash withdrawal is still left uncategorized."""
    services, _ = build(make_settings())
    for f in SyntheticStatements().checking(11, date(2026, 9, 1), months=3):
        services.statements.import_statement("camila", f.content)
    for t in services.ledger.list_transactions("camila").data.transactions:
        text = t.merchant["untrusted_text"]
        if "Transf a Ahorro" in text:
            assert (t.category, t.classifier) == ("savings", "rule"), text
        if "Giro Nacional" in text:
            assert t.category == "uncategorized", (text, t.category)


def test_cartola_command_writes_files_and_touches_no_store(tmp_path, capsys):
    services, _ = build(make_settings())
    assert cli(services, ["cartola", "--seed", "5", "--months", "2", "--out", str(tmp_path)], samples=SyntheticStatements()) == 0
    assert cli(services, ["cartola", "--kind", "card", "--seed", "5", "--out", str(tmp_path)], samples=SyntheticStatements()) == 0
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == ["bice-tarjeta-no-facturado-2026-10-seed5.xlsx", "santander-cuenta-corriente-2026-08-seed5.xlsx", "santander-cuenta-corriente-2026-09-seed5.xlsx"]
    assert services.statements.list_statements(services.default_user).data == ()
    assert "seed 5" in capsys.readouterr().out


def test_seed_refuses_a_memory_store():
    services, _ = build(make_settings(persistence="memory"))
    assert cli(services, ["seed", "--seed", "1"], samples=SyntheticStatements()) == 2
    assert services.statements.list_statements(services.default_user).data == ()


def test_seed_imports_history_and_card_and_is_idempotent_per_seed(tmp_path):
    # uuid ids: a second process on the same database (the API after the seed) must not restart evt_000001.
    settings = make_settings(persistence="sqlite", sqlite_path=str(tmp_path / "seed.db"), ids="uuid")
    services, _ = build(settings)
    assert cli(services, ["seed", "--user", "diego", "--months", "3", "--seed", "4"], samples=SyntheticStatements()) == 0
    statements = services.statements.list_statements("diego").data
    assert len(statements) == 4 and sum(s.provisional for s in statements) == 1
    assert all(s.verified for s in statements)
    assert services.statements.list_statements("camila").data == ()

    reopened, _ = build(settings)  # what the API sees when it starts on the same database
    assert len(reopened.statements.list_statements("diego").data) == 4
    transactions = len(reopened.ledger.list_transactions("diego").data.transactions)
    assert transactions > 0
    assert cli(reopened, ["seed", "--user", "diego", "--months", "3", "--seed", "4"], samples=SyntheticStatements()) == 0
    assert len(reopened.statements.list_statements("diego").data) == 4
    assert len(reopened.ledger.list_transactions("diego").data.transactions) == transactions
