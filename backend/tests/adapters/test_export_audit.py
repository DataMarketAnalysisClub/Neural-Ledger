"""`neural-ledger export-audit`: export the audit log without appending anything to it first."""

from __future__ import annotations

import json

from neural_ledger.adapters.inbound.cli.commands import main as cli
from neural_ledger.adapters.outbound.statements.synthetic import SyntheticStatements
from neural_ledger.bootstrap.container import build
from tests.conftest import make_settings


def test_export_audit_writes_the_trail_as_it_is(tmp_path):
    settings = make_settings(persistence="sqlite", sqlite_path=str(tmp_path / "x.db"), ids="uuid")
    services, _ = build(settings)
    assert cli(services, ["seed", "--user", "diego", "--months", "1", "--seed", "4"], samples=SyntheticStatements()) == 0
    before = services.audit.raw()

    reopened, _ = build(settings)  # a fresh process on the same database, as in the incident runbook
    out = tmp_path / "evidence" / "audit.jsonl"
    assert cli(reopened, ["export-audit", "--out", str(out)]) == 0

    records = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert [r["event_id"] for r in records] == [e.draft.event_id for e in before]  # nothing was run or appended first
    assert len(reopened.audit.raw()) == len(before)
