"""ADR-048 step 6: the declared-memory store. One contract suite, both adapters; then what only SQLite can show
(sealed at rest, bound to its row and owner, durable, migrated, reset)."""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from neural_ledger.adapters.outbound.persistence.field_cipher import FieldCipher, FieldCipherError
from neural_ledger.adapters.outbound.persistence.memory import InMemoryMemoryStore
from neural_ledger.adapters.outbound.persistence.sqlite import (
    SEALED_COLUMNS,
    SqliteDatabase,
    SqliteMemoryStore,
    verify_data_key,
)
from neural_ledger.adapters.outbound.persistence.sqlite_migration import migrate
from neural_ledger.application.ports import IdCollision, MemoryStore
from neural_ledger.domain.memory.catalog import (
    ChatOrigin,
    Declaration,
    MemoryType,
    ProfileOrigin,
    SalaryNet,
    Source,
    StatementOrigin,
    applicable,
    declaration_record,
)
from neural_ledger.domain.shared.month import Month
from tests.conftest import TEST_CIPHER

AT = datetime(2026, 10, 19, 15, 0, tzinfo=UTC)
AMOUNT = 1_234_567  # distinctive: the raw database file must not contain it


def declaration(version: int, amount: int = AMOUNT, effective_from: str = "2026-10", *, chain_id: str = "chn_a",
                user_id: str = "ana", memory_id: str | None = None, origin=None) -> Declaration:
    return Declaration(
        memory_id=memory_id or f"mem_{chain_id}_{version}", chain_id=chain_id, version=version, user_id=user_id,
        value=SalaryNet(amount, Month.parse(effective_from)), confirmed_at=AT, source=Source.CHAT,
        origin=origin or ChatOrigin("s_1", f"msg_{version}"), audit_ref=f"evt_{chain_id}_{version}",
    )


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path) -> MemoryStore:
    if request.param == "memory":
        return InMemoryMemoryStore()
    return SqliteMemoryStore(SqliteDatabase(tmp_path / "memory.db"), TEST_CIPHER)


def test_both_adapters_implement_the_port(store):
    assert isinstance(store, MemoryStore)


def test_a_chain_round_trips_with_every_origin(store):
    base = declaration(1, origin=ChatOrigin("s_1", "msg_1"))
    profile = declaration(2, 1_300_000, "2026-11", origin=ProfileOrigin())
    statement = declaration(3, 1_310_000, "2026-12", origin=StatementOrigin("st_1", "txn_9"))
    assert store.append((base,), 0) is True
    assert store.append((profile,), 1) is True
    assert store.append((statement,), 2) is True
    assert store.chain("ana", "chn_a") == (base, profile, statement)
    assert store.chain_of_type("ana", MemoryType.SALARY_NET) == (base, profile, statement)
    assert store.for_user("ana") == (base, profile, statement)


def test_the_applicable_version_is_selected_from_the_stored_history(store):
    store.append((declaration(1, 1_000_000, "2026-08"), declaration(2, 1_200_000, "2026-11")), 0)
    store.append((declaration(3, 1_250_000, "2026-11"),), 2)  # same effective_from: the later version supersedes
    stored = store.chain("ana", "chn_a")
    assert applicable(stored, Month.parse("2026-10")).version == 1
    assert applicable(stored, Month.parse("2026-11")).version == 3
    assert applicable(stored, Month.parse("2026-07")) is None


def test_a_base_and_a_change_are_stored_together(store):
    batch = (declaration(1, 1_000_000, "2026-09"), declaration(2, 1_200_000, "2026-11"))
    assert store.append(batch, 0) is True
    assert store.chain("ana", "chn_a") == batch


def test_the_export_lists_every_chain_and_version_in_order(store):
    store.append((declaration(1, chain_id="chn_a"),), 0)
    store.append((declaration(2, chain_id="chn_a"),), 1)
    store.append((declaration(1, user_id="bea", chain_id="chn_b"),), 0)
    exported = store.for_user("ana")
    assert [(d.chain_id, d.version) for d in exported] == [("chn_a", 1), ("chn_a", 2)]
    assert [declaration_record(d)["origin"] for d in exported] == [
        {"kind": "chat", "session_id": "s_1", "message_id": "msg_1"},
        {"kind": "chat", "session_id": "s_1", "message_id": "msg_2"},
    ]


# ---- compare-and-set and one chain per user and type ------------------------------------------------------

def test_a_stale_expected_version_writes_nothing(store):
    store.append((declaration(1),), 0)
    assert store.append((declaration(1, memory_id="mem_late"),), 0) is False  # expected a new chain; v1 exists
    store.append((declaration(2),), 1)
    assert store.append((declaration(2, memory_id="mem_stale"),), 1) is False  # the head moved to 2
    assert [d.version for d in store.chain("ana", "chn_a")] == [1, 2]


def test_a_user_cannot_start_a_second_chain_of_the_same_type(store):
    assert store.append((declaration(1, chain_id="chn_a"),), 0) is True
    assert store.append((declaration(1, chain_id="chn_other"),), 0) is False
    assert store.chain("ana", "chn_other") == () and len(store.for_user("ana")) == 1


def test_two_concurrent_first_declarations_create_one_chain(store):
    barrier = threading.Barrier(8)
    results: list[bool] = []

    def first(index: int) -> None:
        barrier.wait()
        results.append(store.append((declaration(1, chain_id=f"chn_{index}"),), 0))

    threads = [threading.Thread(target=first, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(results) == [False] * 7 + [True]
    assert len({d.chain_id for d in store.for_user("ana")}) == 1


def test_two_concurrent_edits_of_the_same_version_append_once(store):
    store.append((declaration(1),), 0)
    barrier = threading.Barrier(6)
    results: list[bool] = []

    def edit(index: int) -> None:
        barrier.wait()
        results.append(store.append((declaration(2, 1_000_000 + index, memory_id=f"mem_edit_{index}"),), 1))

    threads = [threading.Thread(target=edit, args=(i,)) for i in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(results) == [False] * 5 + [True]
    assert [d.version for d in store.chain("ana", "chn_a")] == [1, 2]


# ---- malformed batches and failures leave nothing written -------------------------------------------------

@pytest.mark.parametrize(
    ("batch", "expected"),
    [
        ((), 0),
        ((declaration(2),), 0),  # does not follow the head
        ((declaration(1), declaration(3)), 0),  # a gap
        ((declaration(2), declaration(1)), 0),  # out of order
        ((declaration(1), declaration(2, chain_id="chn_x")), 0),  # two chains
        ((declaration(1), declaration(2, user_id="bea")), 0),  # two owners
        ((declaration(1), declaration(2, memory_id="mem_chn_a_1")), 0),  # one memory_id twice
        ((declaration(1),), -1),
        ((declaration(1),), True),
    ],
)
def test_a_malformed_batch_is_refused_and_writes_nothing(store, batch, expected):
    with pytest.raises(ValueError):
        store.append(batch, expected)
    assert store.for_user("ana") == () and store.for_user("bea") == ()


def test_a_reused_memory_id_in_the_middle_of_a_batch_writes_none_of_it(store):
    store.append((declaration(1, user_id="bea", chain_id="chn_b", memory_id="mem_taken"),), 0)
    with pytest.raises(IdCollision):
        store.append((declaration(1), declaration(2, memory_id="mem_taken")), 0)
    assert store.for_user("ana") == ()
    assert len(store.for_user("bea")) == 1


def test_another_users_chain_id_cannot_be_extended(store):
    store.append((declaration(1, user_id="bea", chain_id="chn_b"),), 0)
    with pytest.raises(IdCollision):
        store.append((declaration(1, chain_id="chn_b"),), 0)
    with pytest.raises(IdCollision):
        store.append((declaration(2, chain_id="chn_b"),), 1)
    assert [d.user_id for d in store.for_user("bea")] == ["bea"] and store.for_user("ana") == ()


def _forged(base: Declaration, **fields) -> Declaration:
    """A declaration changed around its constructor, as a bug or a careless caller could: only the store's own check
    stands between it and a row the codec cannot read back."""
    forged = replace(base)
    for name, value in fields.items():
        object.__setattr__(forged, name, value)
    return forged


def _forged_value(**fields) -> SalaryNet:
    value = SalaryNet(AMOUNT, Month.parse("2026-10"))
    for name, raw in fields.items():
        object.__setattr__(value, name, raw)
    return value


def _forged_origin(origin, **fields):
    for name, raw in fields.items():
        object.__setattr__(origin, name, raw)
    return origin


FORGED = [
    pytest.param({"audit_ref": ""}, id="empty-audit-ref"),  # the reported bug
    pytest.param({"memory_id": ""}, id="empty-memory-id"),
    pytest.param({"chain_id": ""}, id="empty-chain-id"),
    pytest.param({"audit_ref": 42}, id="non-string-audit-ref"),
    pytest.param({"confirmed_by": "agent"}, id="confirmed-by-agent"),
    pytest.param({"source": "chat"}, id="source-not-in-catalog"),
    pytest.param({"confirmed_at": datetime(2026, 10, 19, 15, 0)}, id="naive-confirmed-at"),
    pytest.param({"version": True}, id="boolean-version"),
    pytest.param({"origin": None}, id="no-origin"),
    pytest.param({"origin": _forged_origin(ChatOrigin("s_1", "m"), message_id="")}, id="chat-origin-without-message"),
    pytest.param({"origin": _forged_origin(ChatOrigin("s_1", "m"), session_id=7)}, id="chat-origin-non-string"),
    pytest.param({"origin": _forged_origin(StatementOrigin("st_1", "t"), txn_id="")}, id="statement-origin-without-txn"),
    pytest.param({"value": _forged_value(amount=True)}, id="boolean-amount"),
    pytest.param({"value": _forged_value(amount=0)}, id="zero-amount"),
    pytest.param({"value": _forged_value(amount="1200000")}, id="string-amount"),
    pytest.param({"value": _forged_value(net=False)}, id="gross-salary"),
    pytest.param({"value": _forged_value(effective_from="2026-10")}, id="month-as-string"),
    pytest.param({"value": 1_200_000}, id="bare-amount"),
]


@pytest.mark.parametrize("fields", FORGED)
def test_a_declaration_outside_the_contract_is_refused_before_any_write(store, fields):
    with pytest.raises(ValueError):
        store.append((_forged(declaration(1), **fields),), 0)
    assert store.for_user("ana") == ()
    assert store.append((declaration(1),), 0) is True  # nothing half-written blocks the valid first version


@pytest.mark.parametrize("fields", FORGED[:6])
def test_an_invalid_second_version_writes_neither_version(store, fields):
    with pytest.raises(ValueError):
        store.append((declaration(1), _forged(declaration(2), **fields)), 0)
    assert store.for_user("ana") == ()


def test_an_empty_owner_is_refused(store):
    with pytest.raises(ValueError):
        store.append((_forged(declaration(1), user_id=""),), 0)
    assert store.for_user("") == ()


def test_everything_either_adapter_accepts_reads_back_identically_from_sqlite(tmp_path):
    """Parity: the same accepted batch is returned by the in-memory store and survives SQLite's codec unchanged."""
    batch = (
        declaration(1, 1_000_000, "2026-09", origin=ProfileOrigin()),
        declaration(2, 1_200_000, "2026-11", origin=StatementOrigin("st_1", "txn_9")),
        declaration(3, 1_250_000, "2026-12", origin=ChatOrigin("s_1", "msg_3")),
    )
    memory, sqlite = InMemoryMemoryStore(), _sqlite(tmp_path / "parity.db")
    assert memory.append(batch, 0) and sqlite.append(batch, 0)
    assert memory.chain("ana", "chn_a") == sqlite.chain("ana", "chn_a") == _sqlite(tmp_path / "parity.db").chain("ana", "chn_a") == batch


# ---- no operation reaches another user's data -------------------------------------------------------------

def test_another_users_chain_is_not_found_and_not_deleted(store):
    store.append((declaration(1, user_id="bea", chain_id="chn_b"),), 0)
    assert store.chain("ana", "chn_b") == ()
    assert store.chain_of_type("ana", MemoryType.SALARY_NET) == ()
    assert store.for_user("ana") == ()
    assert store.delete_chain("ana", "chn_b") == 0
    assert len(store.chain("bea", "chn_b")) == 1


def test_deleting_a_chain_removes_every_version_and_frees_the_type(store):
    store.append((declaration(1), declaration(2)), 0)
    store.append((declaration(1, user_id="bea", chain_id="chn_b"),), 0)
    assert store.delete_chain("ana", "chn_a") == 2
    assert store.chain("ana", "chn_a") == () and store.delete_chain("ana", "chn_a") == 0
    assert store.append((declaration(1, chain_id="chn_new"),), 0) is True  # a new chain may start after deletion
    assert len(store.for_user("bea")) == 1


# ---- SQLite only ------------------------------------------------------------------------------------------

def _sqlite(path) -> SqliteMemoryStore:
    return SqliteMemoryStore(SqliteDatabase(path), TEST_CIPHER)


def test_a_failure_after_the_first_insert_of_a_batch_rolls_all_of_it_back(tmp_path):
    """Failure injection inside the write: the trigger fires on version 2 only once version 1 is already in the table
    (the COUNT sees both rows), so the error comes after a real insertion, not from a check that ran before any."""
    db = SqliteDatabase(tmp_path / "partial.db")
    store = SqliteMemoryStore(db, TEST_CIPHER)
    db.connection.execute(
        "CREATE TEMP TRIGGER fail_after_first AFTER INSERT ON main.user_memory "
        "WHEN NEW.version = 2 AND (SELECT COUNT(*) FROM main.user_memory WHERE chain_id = NEW.chain_id) = 2 "
        "BEGIN SELECT RAISE(ABORT, 'injected failure after the first insert'); END"
    )
    with pytest.raises(sqlite3.DatabaseError, match="injected failure"):
        store.append((declaration(1), declaration(2), declaration(3)), 0)
    assert not db.connection.in_transaction
    assert db.counts()["user_memory"] == 0 and store.for_user("ana") == ()
    db.connection.execute("DROP TRIGGER fail_after_first")
    assert store.append((declaration(1),), 0) is True  # the lock was released and the chain can still start


def test_memory_survives_reopening_the_database(tmp_path):
    path = tmp_path / "durable.db"
    stored = (declaration(1, 1_000_000, "2026-09"), declaration(2, 1_200_000, "2026-11"))
    _sqlite(path).append(stored, 0)
    reopened = _sqlite(path)
    assert reopened.chain("ana", "chn_a") == stored
    assert reopened.append((declaration(3),), 2) is True


def test_no_declared_value_is_in_clear_in_the_file(tmp_path):
    path = tmp_path / "sealed.db"
    store = _sqlite(path)
    store.append((declaration(1, origin=ChatOrigin("s_secret_session", "msg_secret")),), 0)
    raw = path.read_bytes() + ((tmp_path / "sealed.db-wal").read_bytes() if (tmp_path / "sealed.db-wal").exists() else b"")
    for needle in (str(AMOUNT), "1234567", "2026-10", "msg_secret", "s_secret_session", "evt_chn_a_1"):
        assert needle.encode() not in raw
    assert "user_memory" in [column.table for column in SEALED_COLUMNS]


@pytest.mark.parametrize(
    "tamper",
    [
        "UPDATE user_memory SET user_id = 'bea'",  # moved to another user
        "UPDATE user_memory SET memory_id = 'mem_other' WHERE version = 1",  # moved to another row id
    ],
)
def test_a_sealed_value_moved_to_another_owner_or_row_does_not_open(tmp_path, tamper):
    db = SqliteDatabase(tmp_path / "moved.db")
    store = SqliteMemoryStore(db, TEST_CIPHER)
    store.append((declaration(1),), 0)
    db.connection.execute(tamper)
    with pytest.raises(FieldCipherError):
        store.for_user("bea") or store.for_user("ana")


def test_a_payload_swapped_between_rows_does_not_open(tmp_path):
    db = SqliteDatabase(tmp_path / "swap.db")
    store = SqliteMemoryStore(db, TEST_CIPHER)
    store.append((declaration(1), declaration(2, 999_999)), 0)
    first, second = (row[0] for row in db.connection.execute("SELECT payload FROM user_memory ORDER BY version"))
    db.connection.execute("UPDATE user_memory SET payload = ? WHERE version = 1", (second,))
    db.connection.execute("UPDATE user_memory SET payload = ? WHERE version = 2", (first,))
    with pytest.raises(FieldCipherError):
        store.chain("ana", "chn_a")


def test_a_clear_column_edited_around_the_application_is_detected(tmp_path):
    db = SqliteDatabase(tmp_path / "edited.db")
    store = SqliteMemoryStore(db, TEST_CIPHER)
    store.append((declaration(1),), 0)
    db.connection.execute("UPDATE user_memory SET version = 7")
    with pytest.raises(FieldCipherError):
        store.chain("ana", "chn_a")


def test_the_database_itself_refuses_a_second_chain_of_a_type(tmp_path):
    db = SqliteDatabase(tmp_path / "unique.db")
    SqliteMemoryStore(db, TEST_CIPHER).append((declaration(1),), 0)
    with pytest.raises(sqlite3.IntegrityError):
        db.connection.execute(
            "INSERT INTO user_memory (memory_id, chain_id, version, user_id, type, payload) VALUES ('m2', 'c2', 1, 'ana', 'salary_net', 'x')"
        )


def test_an_existing_database_without_the_table_gains_it_on_open(tmp_path):
    path = tmp_path / "before.db"
    db = SqliteDatabase(path)
    db.connection.execute("DROP INDEX user_memory_one_chain")
    db.connection.execute("DROP TABLE user_memory")  # a schema-1 file written before ADR-048
    db.connection.execute("INSERT INTO user_profiles (user_id, payload) VALUES ('kept', ?)", (TEST_CIPHER.seal("{}", "user_profiles|kept|kept"),))
    db.connection.close()
    reopened = SqliteDatabase(path)
    assert not reopened.needs_migration
    verify_data_key(reopened, TEST_CIPHER)
    store = SqliteMemoryStore(reopened, TEST_CIPHER)
    assert store.append((declaration(1),), 0) is True
    assert reopened.counts()["user_profiles"] == 1 and reopened.counts()["user_memory"] == 1


def test_the_migration_reseals_memory_under_a_new_key(tmp_path):
    db = SqliteDatabase(tmp_path / "rekey.db")
    SqliteMemoryStore(db, TEST_CIPHER).append((declaration(1),), 0)
    new = FieldCipher(bytes(range(1, 33)))
    report = migrate(db, new, (TEST_CIPHER,))
    assert report.columns["user_memory"].rekeyed == 1
    assert SqliteMemoryStore(db, new).chain("ana", "chn_a") == (declaration(1),)
    with pytest.raises(FieldCipherError):
        SqliteMemoryStore(db, TEST_CIPHER).chain("ana", "chn_a")


def test_a_reset_empties_memory_with_every_other_table(tmp_path):
    db = SqliteDatabase(tmp_path / "reset.db")
    SqliteMemoryStore(db, TEST_CIPHER).append((declaration(1), declaration(2)), 0)
    assert db.reset()["user_memory"] == 2
    assert db.counts()["user_memory"] == 0
