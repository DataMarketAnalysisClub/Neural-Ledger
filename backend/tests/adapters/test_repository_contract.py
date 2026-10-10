"""One contract suite, every adapter: memory and SQLite must behave the same behind the ports."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from neural_ledger.adapters.outbound.persistence.memory import (
    InMemoryActionRepository,
    InMemoryAuditLog,
    InMemorySavingsRuleStore,
)
from neural_ledger.adapters.outbound.persistence.sqlite import (
    SqliteActionRepository,
    SqliteAuditLog,
    SqliteDatabase,
    SqliteSavingsRuleStore,
)
from neural_ledger.domain.actions.terms import (
    ActionTerms,
    ActionType,
    Authorization,
    Frequency,
    Proposal,
    ProposalStatus,
    SavingsRule,
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


@pytest.fixture(params=["memory", "sqlite"])
def rule_store(request, tmp_path):
    if request.param == "memory":
        return InMemorySavingsRuleStore()
    return SqliteSavingsRuleStore(SqliteDatabase(tmp_path / "test.db"))


def _rule(rule_id: str, user_id: str) -> SavingsRule:
    return SavingsRule(rule_id, user_id, 100_000, "CLP", Frequency.MONTHLY, "checking", "sandbox_savings", date(2027, 1, 1), "auth_1")


def test_savings_rules_round_trip_per_user(rule_store):
    rule_store.add(_rule("rule_0001", "camila"))
    rule_store.add(_rule("rule_0002", "diego"))
    rule_store.add(_rule("rule_0003", "camila"))
    assert rule_store.count() == 3
    assert [r.rule_id for r in rule_store.for_user("camila")] == ["rule_0001", "rule_0003"]
    assert rule_store.for_user("camila")[0] == _rule("rule_0001", "camila")
    assert rule_store.for_user("nobody") == ()


def test_sqlite_survives_a_restart(tmp_path):
    """Executed rules, single-use state and the audit chain all outlive the process."""
    path = tmp_path / "durable.db"
    db = SqliteDatabase(path)
    SqliteSavingsRuleStore(db).add(_rule("rule_0001", "camila"))
    repo = SqliteActionRepository(db)
    repo.add_authorization(Authorization("auth_1", "prop_1", "s1", "camila", TERMS, "sig", NOW, NOW + timedelta(minutes=10)))
    assert repo.consume_authorization("auth_1", NOW) is True
    SqliteAuditLog(db).append(AuditDraft("evt_1", NOW, "s1", Actor.SYSTEM, AuditKind.DECISION, detail="x"))
    db.connection.close()

    reopened = SqliteDatabase(path)
    assert SqliteSavingsRuleStore(reopened).for_user("camila") == (_rule("rule_0001", "camila"),)
    assert SqliteActionRepository(reopened).consume_authorization("auth_1", NOW) is False
    assert verify_chain(SqliteAuditLog(reopened).events()).ok
