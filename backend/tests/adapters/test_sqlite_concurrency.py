"""The SQLite adapter shares one connection across request threads; reads must not interleave.

A browser fires several requests at once (the overview loads five resources in parallel).
Before every read went through the database lock, concurrent reads of the same connection
mixed up their cursors and surfaced as IndexError / JSONDecodeError (HTTP 500).
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime

from neural_ledger.adapters.outbound.persistence.sqlite import SqliteAuditLog, SqliteDatabase, SqliteSavingsRuleStore
from neural_ledger.domain.audit.events import Actor, AuditDraft, AuditKind, verify_chain
from tests.conftest import TEST_CIPHER

NOW = datetime(2026, 10, 29, 15, 0, tzinfo=UTC)


def test_concurrent_reads_and_writes_do_not_corrupt_results(tmp_path):
    db = SqliteDatabase(tmp_path / "concurrent.db")
    audit = SqliteAuditLog(db, TEST_CIPHER)
    rules = SqliteSavingsRuleStore(db, TEST_CIPHER)
    for i in range(20):
        audit.append(AuditDraft(f"seed_{i}", NOW, "s1", Actor.SYSTEM, AuditKind.DECISION, detail=str(i)))

    errors: list[BaseException] = []
    start = threading.Barrier(9)

    def reader() -> None:
        start.wait()
        try:
            for _ in range(150):
                events = audit.events()
                assert verify_chain(events).ok
                assert rules.for_user("camila") == ()
                assert rules.count() == 0
        except BaseException as exc:  # noqa: BLE001 - collected and asserted below
            errors.append(exc)

    def writer() -> None:
        start.wait()
        try:
            for i in range(150):
                audit.append(AuditDraft(f"w_{i}", NOW, "s2", Actor.SYSTEM, AuditKind.DECISION, detail=str(i)))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=reader) for _ in range(8)] + [threading.Thread(target=writer)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    events = audit.events()
    assert len(events) == 170 and verify_chain(events).ok
