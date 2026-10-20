"""ADR-048 step 7: a failure at any stage of a memory write leaves nothing written, and what SQLite stores is durable,
sealed, bound to its owner and row, re-keyed by the migration and emptied by a reset."""

from __future__ import annotations

import sqlite3

import pytest

from neural_ledger.adapters.outbound.persistence import memory as memory_adapter
from neural_ledger.adapters.outbound.persistence.field_cipher import FieldCipher, FieldCipherError
from neural_ledger.adapters.outbound.persistence.memory import InMemoryAuditLog
from neural_ledger.adapters.outbound.persistence.sqlite import SEALED_COLUMNS, SqliteDatabase, SqliteMemoryWrites
from neural_ledger.adapters.outbound.persistence.sqlite_migration import migrate
from neural_ledger.domain.memory.consent import Consent
from neural_ledger.domain.memory.proposals import ProposalState
from tests.application.test_memory_writes import AMOUNT, KEY, World

NEW_TABLES = ("memory_state", "memory_proposals")


def _ready(world: World):
    """Ana with consent, one confirmed version and a pending proposal to extend it."""
    world.grant(world.ana)
    assert world.declare(world.ana, month="2026-06").ok
    proposal = world.propose(world.ana, message_id="msg_pending").proposal
    (chain_id,) = {d.chain_id for d in world.store.for_user(world.ana)}
    return proposal, chain_id


def _operations(world: World, proposal, chain_id):
    return {
        "confirm": lambda: world.confirm(world.ana, proposal.proposal_id, expected=1),
        "delete": lambda: world.memory.delete_chain(world.ana, "s_1", chain_id),
        "revoke": lambda: world.memory.set_consent(world.ana, "s_1", {"consent": "revoked"}),
    }


# ---- SQLite: a trigger fails one statement of the transaction ----------------------------------------------

STAGES = {
    "audit insert": "AFTER INSERT ON main.audit_events",
    "state write": "AFTER UPDATE ON main.memory_state",
    "proposal update": "AFTER UPDATE ON main.memory_proposals",
    "declaration insert": "AFTER INSERT ON main.user_memory",
    "declaration delete": "AFTER DELETE ON main.user_memory",
}

UNREACHED = {
    ("confirm", "declaration delete"), ("delete", "declaration insert"),
    ("revoke", "declaration insert"), ("revoke", "declaration delete"),
}


@pytest.mark.parametrize("operation", ["confirm", "delete", "revoke"])
@pytest.mark.parametrize("stage", list(STAGES))
def test_sqlite_a_failure_at_any_stage_rolls_the_whole_write_back(tmp_path, operation, stage):
    world = World("sqlite", tmp_path)
    proposal, chain_id = _ready(world)
    before = world.snapshot(world.ana)
    db: SqliteDatabase = world.store._db
    db.connection.execute(f"CREATE TEMP TRIGGER injected {STAGES[stage]} BEGIN SELECT RAISE(ABORT, 'injected failure'); END")
    if (operation, stage) in UNREACHED:  # that write never runs that statement: it succeeds untouched
        assert _operations(world, proposal, chain_id)[operation]().ok
        return
    with pytest.raises(sqlite3.DatabaseError, match="injected failure"):
        _operations(world, proposal, chain_id)[operation]()
    assert not db.connection.in_transaction
    db.connection.execute("DROP TRIGGER injected")
    assert world.snapshot(world.ana) == before
    assert _operations(world, proposal, chain_id)[operation]().ok  # and the same write then succeeds


# ---- in memory: the same stages fail, and every map is restored ---------------------------------------------

class Injected(RuntimeError):
    pass


def _boom(*_args, **_kwargs):
    raise Injected("injected failure")


@pytest.mark.parametrize("operation", ["confirm", "delete", "revoke"])
@pytest.mark.parametrize("stage", ["audit", "counters"])
def test_in_memory_a_failure_at_any_stage_restores_every_map(tmp_path, monkeypatch, operation, stage):
    world = World("memory", tmp_path)
    proposal, chain_id = _ready(world)
    before = world.snapshot(world.ana)
    if stage == "audit":
        monkeypatch.setattr(InMemoryAuditLog, "append_all", _boom)  # the last step of every write
    else:
        monkeypatch.setattr(memory_adapter, "with_memory_change", _boom)  # after declarations changed
        monkeypatch.setattr(memory_adapter, "consent_detail", _boom)  # after the proposals were invalidated
    with pytest.raises(Injected):
        _operations(world, proposal, chain_id)[operation]()
    monkeypatch.undo()
    assert world.snapshot(world.ana) == before
    assert _operations(world, proposal, chain_id)[operation]().ok


# ---- SQLite only: durable, sealed, bound, migrated, reset --------------------------------------------------

def test_consent_counters_and_proposals_survive_a_restart(tmp_path):
    world = World("sqlite", tmp_path)
    proposal, _ = _ready(world)
    state = world.writes.state(world.ana)
    reopened = SqliteMemoryWrites(SqliteDatabase(tmp_path / "mem.db"), FieldCipher.from_hex(KEY))
    assert reopened.state(world.ana) == state and state.consent is Consent.GRANTED and state.memory_revision == 1
    assert reopened.proposal(world.ana, proposal.proposal_id) == proposal


def test_nothing_personal_of_the_new_tables_is_in_clear_in_the_file(tmp_path):
    world = World("sqlite", tmp_path)
    world.grant(world.ana)
    world.propose(world.ana, candidates=(AMOUNT,), message_id="msg_secret_ref")
    path = tmp_path / "mem.db"
    raw = path.read_bytes() + ((tmp_path / "mem.db-wal").read_bytes() if (tmp_path / "mem.db-wal").exists() else b"")
    for needle in (str(AMOUNT), "msg_secret_ref", "granted", "consent_generation"):
        assert needle.encode() not in raw
    assert set(NEW_TABLES) <= {column.table for column in SEALED_COLUMNS}


@pytest.mark.parametrize("table", ["memory_state", "memory_proposals"])
def test_a_sealed_row_moved_to_another_user_does_not_open(tmp_path, table):
    world = World("sqlite", tmp_path)
    proposal, _ = _ready(world)
    db: SqliteDatabase = world.store._db
    db.connection.execute(f"UPDATE {table} SET user_id = ? WHERE user_id = ?", (world.bea, world.ana))
    with pytest.raises(FieldCipherError):
        world.writes.state(world.bea) if table == "memory_state" else world.writes.proposal(world.bea, proposal.proposal_id)


def test_a_proposal_payload_swapped_into_another_row_does_not_open(tmp_path):
    world = World("sqlite", tmp_path)
    first, _ = _ready(world)
    second = world.propose(world.ana, message_id="msg_other").proposal
    db: SqliteDatabase = world.store._db
    payload = db.connection.execute("SELECT payload FROM memory_proposals WHERE proposal_id = ?", (first.proposal_id,)).fetchone()[0]
    db.connection.execute("UPDATE memory_proposals SET payload = ? WHERE proposal_id = ?", (payload, second.proposal_id))
    with pytest.raises(FieldCipherError):
        world.writes.proposal(world.ana, second.proposal_id)


def test_the_migration_reseals_the_new_tables_under_a_new_key(tmp_path):
    world = World("sqlite", tmp_path)
    proposal, _ = _ready(world)
    db: SqliteDatabase = world.store._db
    old, new = FieldCipher.from_hex(KEY), FieldCipher(bytes(range(7, 39)))
    report = migrate(db, new, (old,))
    assert report.columns["memory_state"].rekeyed == 1 and report.columns["memory_proposals"].rekeyed == 1
    assert SqliteMemoryWrites(db, new).proposal(world.ana, proposal.proposal_id).state is ProposalState.PENDING
    with pytest.raises(FieldCipherError):
        SqliteMemoryWrites(db, old).state(world.ana)


def test_a_reset_empties_the_new_tables(tmp_path):
    world = World("sqlite", tmp_path)
    _ready(world)
    db: SqliteDatabase = world.store._db
    deleted = db.reset()
    assert deleted["memory_state"] == 1 and deleted["memory_proposals"] == 1
    assert all(db.counts()[table] == 0 for table in NEW_TABLES)
