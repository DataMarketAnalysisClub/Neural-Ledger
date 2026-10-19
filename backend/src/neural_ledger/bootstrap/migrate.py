"""`neural-ledger migrate-data`: move the SQLite file to the configured data key (operators, run once per server).

It runs before the application is built, so the checks that refuse to start with an old key file do not stop it.
Stop the API first (`docker compose stop api`): the migration takes the write lock for the whole run.

    neural-ledger migrate-data --dry-run          # what would change; writes nothing
    neural-ledger migrate-data                    # re-seal everything with the new key, then VACUUM
    neural-ledger migrate-data --old-key-file F   # another old key file than <db>.key

The new key comes from the same place as the app's (bootstrap/data_key.py): the Docker secret, NL_DATA_KEY_FILE
or NL_DATA_KEY. The old one defaults to `<NL_SQLITE_PATH>.key`, the file offline runs created next to the database.
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Callable
from pathlib import Path

from ..adapters.outbound.persistence.field_cipher import FieldCipher, FieldCipherError
from ..adapters.outbound.persistence.sqlite import SqliteDatabase
from ..adapters.outbound.persistence.sqlite_migration import migrate
from . import data_key
from .config import Settings


def _read_key(path: Path) -> FieldCipher:
    try:
        return FieldCipher.from_hex(path.read_text(encoding="ascii"))
    except (OSError, UnicodeDecodeError) as exc:
        raise SystemExit(f"migrate-data: cannot read the old key file {path} ({exc.__class__.__name__})") from None


def main(argv: list[str], settings: Settings | None = None, out: Callable[[str], None] = print) -> int:
    parser = argparse.ArgumentParser(prog="neural-ledger migrate-data", description="Re-seal the SQLite data with the configured data key.")
    parser.add_argument("--dry-run", action="store_true", help="report what would change and write nothing")
    parser.add_argument("--old-key-file", type=Path, help="the old key (default: <NL_SQLITE_PATH>.key, when it exists)")
    args = parser.parse_args(argv)

    s = settings or Settings.from_env()
    if s.persistence != "sqlite" or s.sqlite_path == ":memory:":
        out("migrate-data: NL_PERSISTENCE=sqlite and a file NL_SQLITE_PATH are needed")
        return 2
    database = Path(s.sqlite_path)
    if not database.is_file():
        out(f"migrate-data: no database at {database}")
        return 2
    try:
        key = data_key.resolve(s)
    except data_key.DataKeyError as error:
        out(f"migrate-data: {error}")
        return 2
    legacy = data_key.legacy_key_file(s.sqlite_path)
    if key is None:
        out("migrate-data: no new key. Mount the Docker secret, or set NL_DATA_KEY_FILE or NL_DATA_KEY (64 hex characters)")
        return 2
    if key.path is not None and legacy.exists() and os.path.samefile(key.path, legacy):
        out(f"migrate-data: the new key is the old key file {legacy}; generate a new key outside the data volume")
        return 2
    try:
        new = FieldCipher.from_hex(key.hex)
    except ValueError as error:
        out(f"migrate-data: the new key ({key.source}) is not valid: {error}")
        return 2
    old_path = args.old_key_file or (legacy if legacy.exists() else None)
    if args.old_key_file is not None and not args.old_key_file.is_file():
        out(f"migrate-data: no old key file at {args.old_key_file}")
        return 2
    old = [_read_key(old_path)] if old_path else []

    out(f"migrate-data: database {database}; new key from {key.source}; old key {old_path or 'none'}{' (dry run)' if args.dry_run else ''}")
    try:
        report = migrate(SqliteDatabase(database), new, old, dry_run=args.dry_run)
    except FieldCipherError as error:
        out(f"migrate-data: {error}")
        return 1
    for table, column in report.columns.items():
        out(f"  {table:<16} already current {column.current:>6}   re-keyed {column.rekeyed:>6}   sealed from plain text {column.sealed:>6}")
    verb = "would change" if args.dry_run else "changed"
    out(f"migrate-data: {verb} {report.changed} value(s); the key check is {'unchanged (dry run)' if args.dry_run else 'written for the new key'}")
    if args.dry_run:
        out("migrate-data: nothing was written. Run again without --dry-run to migrate.")
    elif old_path:
        out(
            f"migrate-data: every value now opens with the new key. DELETE THE OLD KEY FILE NOW: {old_path}\n"
            "  (Docker: docker compose run --rm api rm -f /app/var/neural_ledger.db.key). "
            "NL_DEPLOYMENT=deployed refuses to start while it exists."
        )
    return 0
