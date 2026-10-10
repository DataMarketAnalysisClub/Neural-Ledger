"""One contract suite, every adapter: memory and SQLite must behave the same behind the ports."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from neural_ledger.adapters.outbound.persistence.memory import (
    InMemoryActionRepository,
    InMemoryAuditLog,
)
from neural_ledger.adapters.outbound.persistence.sqlite import (
    SqliteActionRepository,
    SqliteAuditLog,
    SqliteDatabase,
)
from neural_ledger.domain.actions.terms import (
    ActionTerms,
    ActionType,
    Authorization,
    Frequency,
    Proposal,
    ProposalStatus,
)
from neural_ledger.domain.audit.events import Actor, AuditDraft, AuditKind, verify_chain

NOW = datetime(2026, 10, 29, 15, 0, tzinfo=UTC)
TERMS = ActionTerms(ActionType.CREATE_SAVINGS_RULE, 100_000, "CLP", Frequency.MONTHLY, "checking", "sandbox_savings", date(2027, 1, 1))


@pytest.fixture(params=["memory", "sqlite"])
def stores(request, tmp_path):
    if request.param == "memory":
        return InMemoryActionRepository(), InMemoryAuditLog()
    db = SqliteDatabase(tmp_path / "test.db")
    return SqliteActionRepository(db), SqliteAuditLog(db)


def test_proposal_round_trip(stores):
    repo, _ = stores
    p = Proposal("prop_1", "s1", "camila", TERMS, "plan_x", NOW, NOW + timedelta(minutes=30))
    repo.add_proposal(p)
    assert repo.get_proposal("prop_1") == p
    repo.update_proposal(replace(p, status=ProposalStatus.CONFIRMED))
    assert repo.get_proposal("prop_1").status is ProposalStatus.CONFIRMED
    assert repo.for_session("s1")[0][0].proposal_id == "prop_1"


def test_authorization_is_single_use(stores):
    repo, _ = stores
    a = Authorization("auth_1", "prop_1", "s1", "camila", TERMS, "sig", NOW, NOW + timedelta(minutes=10))
    repo.add_authorization(a)
    assert repo.get_authorization("auth_1") == a
    assert repo.consume_authorization("auth_1", NOW) is True
    assert repo.consume_authorization("auth_1", NOW) is False
    assert repo.get_authorization("auth_1").consumed_at == NOW
    assert repo.consume_authorization("missing", NOW) is False


def test_audit_log_is_a_valid_chain(stores):
    _, audit = stores
    for i in range(5):
        audit.append(AuditDraft(f"evt_{i}", NOW, "s1" if i % 2 else "s2", Actor.SYSTEM, AuditKind.DECISION, detail=str(i)))
    events = audit.events()
    assert [e.sequence for e in events] == [1, 2, 3, 4, 5]
    assert verify_chain(events).ok
    assert [e.draft.event_id for e in audit.events("s1")] == ["evt_1", "evt_3"]
