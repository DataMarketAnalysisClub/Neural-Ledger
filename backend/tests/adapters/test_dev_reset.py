"""`neural-ledger reset`: a developer command that empties the SQLite database in place."""

from __future__ import annotations

import builtins

import pytest

from neural_ledger.adapters.inbound.cli.commands import main as cli
from neural_ledger.adapters.outbound.persistence.sqlite import SqliteDatabase
from neural_ledger.adapters.outbound.statements.synthetic import SyntheticStatements
from neural_ledger.bootstrap.container import build
from tests.conftest import make_settings

SEED = ["seed", "--user", "diego", "--months", "2", "--seed", "4"]


class Local:
    """What bootstrap passes in: the database at a path."""

    def __init__(self, path: str) -> None:
        self.path = path

    def counts(self):
        return SqliteDatabase(self.path).counts()

    def reset(self):
        return SqliteDatabase(self.path).reset()


def _seeded(tmp_path):
    # uuid ids: a second build on the same file must not restart sequential event ids.
    settings = make_settings(persistence="sqlite", sqlite_path=str(tmp_path / "x.db"), ids="uuid")
    services, _ = build(settings)
    assert cli(services, SEED, samples=SyntheticStatements()) == 0
    return settings, services, Local(settings.sqlite_path)


def _total(settings) -> int:
    return sum(SqliteDatabase(settings.sqlite_path).counts().values())


def test_reset_refuses_a_memory_store(tmp_path):
    services, _ = build(make_settings(persistence="memory"))
    database = Local(str(tmp_path / "never.db"))
    assert cli(services, ["reset", "--yes"], database=database) == 2
    assert not (tmp_path / "never.db").exists()


def test_reset_yes_empties_every_table_and_a_fresh_build_sees_nothing(tmp_path):
    settings, services, database = _seeded(tmp_path)
    assert _total(settings) > 0
    assert cli(services, ["reset", "--yes"], database=database) == 0
    counts = SqliteDatabase(settings.sqlite_path).counts()
    assert counts and all(rows == 0 for rows in counts.values())
    fresh, _ = build(settings)
    assert fresh.statements.list_statements("diego").data == ()
    assert fresh.ledger.list_transactions("diego").data.transactions == ()


@pytest.mark.parametrize("answer", ["n", "", "maybe"])
def test_declining_keeps_every_row(tmp_path, monkeypatch, answer):
    settings, services, database = _seeded(tmp_path)
    before = SqliteDatabase(settings.sqlite_path).counts()
    monkeypatch.setattr(builtins, "input", lambda prompt="": answer)
    assert cli(services, ["reset"], database=database) == 1
    assert SqliteDatabase(settings.sqlite_path).counts() == before


def test_a_non_interactive_stdin_counts_as_no(tmp_path, monkeypatch):
    settings, services, database = _seeded(tmp_path)
    before = SqliteDatabase(settings.sqlite_path).counts()

    def no_stdin(prompt=""):
        raise EOFError

    monkeypatch.setattr(builtins, "input", no_stdin)
    assert cli(services, ["reset"], database=database) == 1
    assert SqliteDatabase(settings.sqlite_path).counts() == before


def test_confirming_with_y_deletes(tmp_path, monkeypatch, capsys):
    settings, services, database = _seeded(tmp_path)
    monkeypatch.setattr(builtins, "input", lambda prompt="": "y")
    assert cli(services, ["reset"], database=database) == 0
    assert _total(settings) == 0
    assert "Restart the API" in capsys.readouterr().out


def test_seed_works_again_and_the_audit_chain_verifies(tmp_path):
    settings, services, database = _seeded(tmp_path)
    assert cli(services, ["reset", "--yes"], database=database) == 0
    again, _ = build(settings)
    assert cli(again, SEED, samples=SyntheticStatements()) == 0
    assert len(again.statements.list_statements("diego").data) > 0
    assert again.audit.verify().ok


def test_reset_on_an_empty_database_exits_without_asking(tmp_path, monkeypatch):
    settings = make_settings(persistence="sqlite", sqlite_path=str(tmp_path / "x.db"), ids="uuid")
    services, _ = build(settings)

    def fail(prompt=""):
        raise AssertionError("must not prompt")

    monkeypatch.setattr(builtins, "input", fail)
    assert cli(services, ["reset"], database=Local(settings.sqlite_path)) == 0


def test_database_reset_returns_per_table_counts(tmp_path):
    settings, _, _ = _seeded(tmp_path)
    db = SqliteDatabase(settings.sqlite_path)
    before = db.counts()
    deleted = db.reset()
    assert deleted == before and sum(deleted.values()) > 0
    assert set(db.counts()) == set(before) and sum(db.counts().values()) == 0


def test_a_table_reset_does_not_know_makes_it_refuse_and_delete_nothing(tmp_path):
    settings, _, _ = _seeded(tmp_path)
    db = SqliteDatabase(settings.sqlite_path)
    db.connection.execute("CREATE TABLE brand_new (id TEXT)")
    rows = db.connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    assert rows > 0
    with pytest.raises(RuntimeError, match="brand_new"):
        db.reset()
    with pytest.raises(RuntimeError, match="brand_new"):
        db.counts()
    assert db.connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == rows


def test_reset_sql_covers_exactly_the_tables_the_schema_creates(tmp_path):
    from neural_ledger.adapters.outbound.persistence.sqlite import _RESET_SQL

    assert set(_RESET_SQL) == set(SqliteDatabase(tmp_path / "fresh.db").counts())
