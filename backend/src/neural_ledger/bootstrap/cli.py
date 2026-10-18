"""CLI entrypoint: `neural-ledger demo` or `python -m neural_ledger.bootstrap.cli demo`."""

from __future__ import annotations

import sys
from collections.abc import Mapping

from ..adapters.inbound.cli.commands import main as run
from ..adapters.outbound.persistence.sqlite import SqliteDatabase
from ..adapters.outbound.statements.synthetic import SyntheticStatements
from .config import Settings
from .container import build_services


class LocalDatabase:
    """The SQLite file the settings point at, opened only when `reset` runs."""

    def __init__(self, path: str) -> None:
        self.path = path

    def counts(self) -> Mapping[str, int]:
        return SqliteDatabase(self.path).counts()

    def reset(self) -> Mapping[str, int]:
        return SqliteDatabase(self.path).reset()


def main(argv: list[str] | None = None) -> int:
    settings = Settings.from_env()
    database = LocalDatabase(settings.sqlite_path) if settings.persistence == "sqlite" else None
    return run(build_services(settings), argv, samples=SyntheticStatements(), database=database)


if __name__ == "__main__":
    sys.exit(main())
