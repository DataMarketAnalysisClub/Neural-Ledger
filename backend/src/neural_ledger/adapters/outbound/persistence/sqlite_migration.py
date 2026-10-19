"""One-shot data migration for the SQLite file: the current schema, and every sealed column sealed with the new key.

First the schema is brought to SCHEMA_VERSION (sqlite.upgrade_schema). Then, for each value in SEALED_COLUMNS (sqlite.py):
- already sealed with the new key, in the current format: left alone;
- sealed with an old key (the offline `<db>.key` file): opened with it and sealed again with the new key;
- plain text (written before that column was sealed): sealed with the new key.
A value that opens with no key it was given stops the migration, and nothing is written.

Everything runs in one transaction, so a failure or a dry run leaves the file as it was. Running it again
changes nothing (idempotent). After a real run that changed something, VACUUM and a WAL checkpoint rewrite
the file, so free pages and the write-ahead log keep no copy of the old plaintext or old ciphertext.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from .field_cipher import FieldCipher, FieldCipherError, WrongDataKey
from .sqlite import SCHEMA_VERSION, SEALED_COLUMNS, SqliteDatabase, upgrade_schema, write_key_check


@dataclass
class ColumnReport:
    current: int = 0  # already sealed with the new key
    rekeyed: int = 0  # opened with an old key, sealed with the new one
    sealed: int = 0  # plain text, now sealed

    @property
    def changed(self) -> int:
        return self.rekeyed + self.sealed


@dataclass
class MigrationReport:
    dry_run: bool
    schema_from: int = SCHEMA_VERSION  # the version the file had; SCHEMA_VERSION when there was nothing to upgrade
    columns: dict[str, ColumnReport] = field(default_factory=dict)

    @property
    def changed(self) -> int:
        return sum(c.changed for c in self.columns.values()) + (self.schema_from < SCHEMA_VERSION)


def _plaintext(value: str, aad: str, new: FieldCipher, old: Sequence[FieldCipher], where: str) -> tuple[str, str]:
    """(plaintext, how): how is current, rekeyed or sealed."""
    if not new.is_sealed(value):
        return value, "sealed"
    try:
        opened = new.open(value, aad)
        return opened, "current" if new.is_current(value) else "rekeyed"
    except FieldCipherError:
        pass
    for cipher in old:
        try:
            return cipher.open(value, aad), "rekeyed"
        except FieldCipherError:
            continue
    raise WrongDataKey(f"{where} opens with neither the new key nor an old one; nothing was changed")


def migrate(db: SqliteDatabase, new: FieldCipher, old: Sequence[FieldCipher] = (), *, dry_run: bool = False) -> MigrationReport:
    report = MigrationReport(dry_run)
    with db.lock:
        conn = db.connection
        conn.execute("BEGIN IMMEDIATE")
        try:
            report.schema_from = upgrade_schema(conn, new)
            for column in SEALED_COLUMNS:
                counts = report.columns.setdefault(column.table, ColumnReport())
                for record in conn.execute(column.select).fetchall():
                    value, aad = record[-1], column.aad(record)
                    plaintext, how = _plaintext(value, aad, new, old, f"{column.table} row {record[0]}")
                    if how == "current":
                        counts.current += 1
                        continue
                    setattr(counts, how, getattr(counts, how) + 1)
                    conn.execute(column.update, (new.seal(plaintext, aad), record[0]))
            write_key_check(conn, new)
            conn.execute("ROLLBACK" if dry_run else "COMMIT")
            if not dry_run:
                db.schema_version = SCHEMA_VERSION
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        if not dry_run and report.changed:
            conn.execute("VACUUM")  # free pages may still hold the values as they were before
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return report
