"""One contract for both investment stores (ADR-044): compare-and-set writes that land with their audit events or not
at all, bounded history, and, in SQLite, nothing readable on disk."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

pytest.importorskip("cryptography")

from neural_ledger.adapters.outbound.persistence import memory as memory_module  # noqa: E402
from neural_ledger.adapters.outbound.persistence import sqlite as sqlite_module  # noqa: E402
from neural_ledger.adapters.outbound.persistence.memory import InMemoryAuditLog, InMemoryInvestmentStore  # noqa: E402
from neural_ledger.adapters.outbound.persistence.sqlite import SqliteAuditLog, SqliteDatabase, SqliteInvestmentStore  # noqa: E402
from neural_ledger.application.ports import IdCollision  # noqa: E402
from neural_ledger.domain.audit.events import Actor, AuditDraft, AuditKind  # noqa: E402
from neural_ledger.domain.investments.model import InvestmentLink, ReportedGoal, snapshot_from_report  # noqa: E402
from tests.conftest import TEST_CIPHER  # noqa: E402

AT = datetime(2026, 10, 29, 15, 0, tzinfo=UTC)
USER = "usr_store"
EMAIL = "store.owner@example.invalid"
TOKEN = "synthetic-token-7f3a9c21"
GOAL_NAME = "Meta secreta de prueba"


def _link(user: str = USER, **changes) -> InvestmentLink:
    return replace(InvestmentLink(user, "fintual", "fintual", EMAIL, TOKEN, AT), **changes)


def _snapshot(user: str = USER, minutes: int = 0, value: str = "1000"):
    goals = (ReportedGoal("1", GOAL_NAME, Decimal(value), Decimal("800")),)
    return snapshot_from_report(user, "fintual", "CLP", AT + timedelta(minutes=minutes), goals)


def _event(event_id: str, user: str = USER, kind: AuditKind = AuditKind.INVESTMENTS_LINKED) -> AuditDraft:
    return AuditDraft(event_id=event_id, timestamp=AT, session_id="sess", user_id=user, actor=Actor.USER, kind=kind, detail="provider=fintual")


@pytest.fixture(params=["memory", "sqlite"])
def backend(request, tmp_path):
    if request.param == "memory":
        audit = InMemoryAuditLog()
        return InMemoryInvestmentStore(audit), audit, None
    path = tmp_path / "investments.db"
    db = SqliteDatabase(path)
    return SqliteInvestmentStore(db, TEST_CIPHER), SqliteAuditLog(db, TEST_CIPHER), path


def _kinds(audit) -> list[str]:
    return [e.draft.kind.value for e in audit.events()]


def test_save_reads_back_and_commits_its_events(backend):
    store, audit, _ = backend
    assert store.link(USER) is None and store.latest(USER) is None
    assert store.save(None, _link(), _snapshot(), (_event("evt_1"),))
    assert store.link(USER) == _link() and store.latest(USER) == _snapshot()
    assert _kinds(audit) == ["INVESTMENTS_LINKED"]
    newer = _snapshot(minutes=5, value="1100")
    assert store.save(_link(), _link(), newer, (_event("evt_2", kind=AuditKind.INVESTMENTS_SYNCED),))
    assert store.latest(USER) == newer and _kinds(audit) == ["INVESTMENTS_LINKED", "INVESTMENTS_SYNCED"]


def test_a_stale_expectation_writes_nothing(backend):
    store, audit, _ = backend
    assert store.save(None, _link(), _snapshot(), (_event("evt_1"),))
    assert not store.save(None, _link(token="another"), _snapshot(minutes=1), (_event("evt_2"),))
    assert not store.save(_link(expired=True), _link(token="another"), None, ())
    assert store.link(USER) == _link() and store.latest(USER) == _snapshot() and _kinds(audit) == ["INVESTMENTS_LINKED"]


def test_a_link_can_be_marked_expired_without_a_snapshot_or_an_event(backend):
    store, audit, _ = backend
    store.save(None, _link(), _snapshot(), (_event("evt_1"),))
    assert store.save(_link(), _link(expired=True), None, ())
    assert store.link(USER).expired and store.latest(USER) == _snapshot() and _kinds(audit) == ["INVESTMENTS_LINKED"]


def test_another_users_link_snapshot_or_event_is_refused_and_nothing_lands(backend):
    store, audit, _ = backend
    for args in (
        (None, _link(), _snapshot(user="usr_other"), ()),
        (None, _link(), None, (_event("evt_x", user="usr_other"),)),
        (_link(user="usr_other"), _link(), None, ()),
    ):
        with pytest.raises(ValueError):
            store.save(*args)
    with pytest.raises(ValueError):
        store.remove(USER, (_event("evt_y", user="usr_other"),))
    assert store.link(USER) is None and _kinds(audit) == []


def test_a_reused_event_id_writes_nothing(backend):
    store, audit, _ = backend
    store.save(None, _link(), _snapshot(), (_event("evt_1"),))
    with pytest.raises(IdCollision):
        store.save(_link(), _link(token="new"), _snapshot(minutes=1), (_event("evt_1"),))
    assert store.link(USER) == _link() and store.latest(USER) == _snapshot() and _kinds(audit) == ["INVESTMENTS_LINKED"]


def test_remove_deletes_the_link_and_every_snapshot_with_its_event(backend):
    store, audit, _ = backend
    store.save(None, _link(), _snapshot(), (_event("evt_1"),))
    store.save(_link(), _link(), _snapshot(minutes=1), ())
    assert store.save(None, _link(user="usr_other"), _snapshot(user="usr_other"), (_event("evt_2", user="usr_other"),))
    assert store.remove(USER, (_event("evt_3", kind=AuditKind.INVESTMENTS_UNLINKED),)) == 3
    assert store.link(USER) is None and store.latest(USER) is None
    assert store.link("usr_other") is not None  # only the caller's rows go
    assert store.remove(USER, (_event("evt_4", kind=AuditKind.INVESTMENTS_UNLINKED),)) == 0  # nothing linked: no event
    assert _kinds(audit) == ["INVESTMENTS_LINKED", "INVESTMENTS_LINKED", "INVESTMENTS_UNLINKED"]


def test_history_keeps_only_the_newest_snapshots(backend, monkeypatch):
    store, _, _ = backend
    monkeypatch.setattr(memory_module, "MAX_SNAPSHOTS", 3)
    monkeypatch.setattr(sqlite_module, "MAX_SNAPSHOTS", 3)
    store.save(None, _link(), _snapshot(), ())
    for minutes in range(1, 6):
        store.save(_link(), _link(), _snapshot(minutes=minutes), ())
    assert store.latest(USER) == _snapshot(minutes=5)
    if isinstance(store, SqliteInvestmentStore):
        rows = store._db.fetchall("SELECT COUNT(*) FROM investment_snapshots WHERE user_id = ?", (USER,))
        assert rows[0][0] == 3
    else:
        assert len(store._snapshots[USER]) == 3


def test_sqlite_keeps_nothing_readable_on_disk(tmp_path):
    path = tmp_path / "sealed.db"
    db = SqliteDatabase(path)
    store = SqliteInvestmentStore(db, TEST_CIPHER)
    store.save(None, _link(), _snapshot(), (_event("evt_1"),))
    raw = _raw(path)
    for secret in (EMAIL, TOKEN, GOAL_NAME):  # long and distinctive: a short number could appear in ciphertext by chance
        assert secret.encode("utf-8") not in raw, secret
    store.remove(USER, (_event("evt_2", kind=AuditKind.INVESTMENTS_UNLINKED),))
    assert db.fetchall("SELECT COUNT(*) FROM investment_links")[0][0] == 0


def test_a_sealed_link_does_not_open_in_another_users_row(tmp_path):
    db = SqliteDatabase(tmp_path / "bound.db")
    store = SqliteInvestmentStore(db, TEST_CIPHER)
    store.save(None, _link(), None, ())
    with db.lock:
        db.connection.execute("INSERT INTO investment_links (user_id, payload) SELECT 'usr_thief', payload FROM investment_links")
    with pytest.raises(Exception):  # noqa: B017 - FieldCipherError: the associated data names the owner
        store.link("usr_thief")


def _raw(path: Path) -> bytes:
    wal = path.with_name(path.name + "-wal")
    return path.read_bytes() + (wal.read_bytes() if wal.exists() else b"")


# ---- imported documents (the statement import path) ------------------------------------------------------


def _document(user: str = USER, document_id: str = "invdoc_0000000000000001", day: int = 14):
    from neural_ledger.domain.investments.documents import FundMovement, FundPosition, InvestmentDocumentKind, StoredInvestmentDocument

    movement = FundMovement(
        datetime(2026, 9, 15).date(), GOAL_NAME, "Moderate Pitt", "A", Decimal("20.0000"), Decimal(0), Decimal("2250.1234"),
        Decimal("35.0000"), 45_002, 0, False, 78_754,
    )
    return StoredInvestmentDocument(
        document_id, user, "fintual", InvestmentDocumentKind.MOVEMENTS, AT, datetime(2026, 10, day).date(),
        positions=(FundPosition("Risky Norris", "A", Decimal("62.7235"), Decimal("4800.0000"), 301_073),),
        total=301_073, movements=(movement,),
    )


def test_documents_read_back_exactly_with_their_events(backend):
    store, audit, _ = backend
    assert store.documents(USER) == ()
    assert store.add_document(_document(), (_event("evt_1", kind=AuditKind.INVESTMENT_DOCUMENT_IMPORTED),))
    assert store.documents(USER) == (_document(),)  # decimals and dates survive the round trip exactly
    assert _kinds(audit) == ["INVESTMENT_DOCUMENT_IMPORTED"]


def test_the_same_document_is_stored_once_and_its_event_is_not_written(backend):
    store, audit, _ = backend
    assert store.add_document(_document(), (_event("evt_1", kind=AuditKind.INVESTMENT_DOCUMENT_IMPORTED),))
    assert not store.add_document(_document(), (_event("evt_2", kind=AuditKind.INVESTMENT_DOCUMENT_IMPORTED),))
    assert store.add_document(_document(user="usr_other"), ())  # the same id belongs to each user separately
    assert len(store.documents(USER)) == 1 and _kinds(audit) == ["INVESTMENT_DOCUMENT_IMPORTED"]


def test_documents_keep_only_the_newest_imports(backend, monkeypatch):
    store, _, _ = backend
    monkeypatch.setattr(memory_module, "MAX_DOCUMENTS", 2)
    monkeypatch.setattr(sqlite_module, "MAX_DOCUMENTS", 2)
    for n in range(1, 5):
        store.add_document(_document(document_id=f"invdoc_{n:016x}"), ())
    assert [d.document_id for d in store.documents(USER)] == ["invdoc_0000000000000003", "invdoc_0000000000000004"]


def test_another_users_document_or_event_is_refused(backend):
    store, audit, _ = backend
    with pytest.raises(ValueError):
        store.add_document(_document(), (_event("evt_x", user="usr_other"),))
    with pytest.raises(ValueError):
        store.remove_documents(USER, (_event("evt_y", user="usr_other"),))
    assert store.documents(USER) == () and _kinds(audit) == []


def test_unlinking_keeps_the_documents_and_removing_them_keeps_the_link(backend):
    store, audit, _ = backend
    store.save(None, _link(), _snapshot(), (_event("evt_1"),))
    store.add_document(_document(), ())
    store.add_document(_document(user="usr_other"), ())
    assert store.remove(USER, (_event("evt_2", kind=AuditKind.INVESTMENTS_UNLINKED),)) == 2
    assert len(store.documents(USER)) == 1
    assert store.remove_documents(USER, (_event("evt_3", kind=AuditKind.INVESTMENT_DOCUMENTS_REMOVED),)) == 1
    assert store.documents(USER) == () and len(store.documents("usr_other")) == 1
    assert store.remove_documents(USER, (_event("evt_4", kind=AuditKind.INVESTMENT_DOCUMENTS_REMOVED),)) == 0  # none left: no event
    assert _kinds(audit) == ["INVESTMENTS_LINKED", "INVESTMENTS_UNLINKED", "INVESTMENT_DOCUMENTS_REMOVED"]


def test_sqlite_keeps_no_document_readable_on_disk(tmp_path):
    path = tmp_path / "sealed-documents.db"
    db = SqliteDatabase(path)
    store = SqliteInvestmentStore(db, TEST_CIPHER)
    store.add_document(_document(), ())
    raw = _raw(path)
    for secret in (GOAL_NAME, "Moderate Pitt", "2250.1234", "62.7235"):
        assert secret.encode("utf-8") not in raw, secret
    with db.lock:  # the associated data names the owner: a row copied to another user does not open
        db.connection.execute(
            "INSERT INTO investment_documents (document_id, user_id, payload) SELECT document_id, 'usr_thief', payload FROM investment_documents"
        )
    with pytest.raises(Exception):  # noqa: B017 - FieldCipherError
        store.documents("usr_thief")
