"""CLI entrypoint: `neural-ledger demo` or `python -m neural_ledger.bootstrap.cli demo`."""

from __future__ import annotations

import sys

from ..adapters.inbound.cli.commands import main as run
from .container import build_services


def main(argv: list[str] | None = None) -> int:
    return run(build_services(), argv)


if __name__ == "__main__":
    sys.exit(main())
