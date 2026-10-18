"""One contract suite, every adapter: memory and SQLite must behave the same behind the ports."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from neural_ledger.adapters.outbound.persistence.field_cipher import FieldCipher
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
TEST_CIPHER = FieldCipher(bytes(range(32)))
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


@pytest.fixture(params=["memory", "sqlite"])
def statement_store(request, tmp_path):
    from neural_ledger.adapters.outbound.persistence.memory import InMemoryStatementStore
    from neural_ledger.adapters.outbound.persistence.sqlite import SqliteStatementStore

    if request.param == "memory":
        return InMemoryStatementStore()
    return SqliteStatementStore(SqliteDatabase(tmp_path / "test.db"), TEST_CIPHER)


def _stored(statement_id: str = "stmt_1", user_id: str = "camila"):
    from neural_ledger.domain.statements.model import (
        BankStatement,
        DailyBalance,
        Issue,
        IssueCode,
        StatementLine,
        StatementSummary,
        StoredStatement,
    )

    statement = BankStatement(
        bank="test",
        account_ref="0-000-00-00000-0",
        currency="CLP",
        period_start=date(2026, 8, 31),
        period_end=date(2026, 9, 30),
        lines=(
            StatementLine(0, date(2026, 9, 2), "Compra Nacional MD SHOP", -3_280, "2441010", "401"),
            StatementLine(1, date(2026, 9, 4), "PAGO PROVEEDOR", 163_521, None, "90", 0.734512),
        ),
        summary=StatementSummary(1_000_000, 3_280, 163_521, 1_160_241),
        daily_balances=(DailyBalance(date(2026, 9, 2), 996_720),),
        statement_number="64",
        source="ocr",
    )
    issues = (Issue(IssueCode.DAILY_BALANCE, "differs", 996_720, 996_721, date(2026, 9, 2)),)
    return StoredStatement(statement_id, user_id, NOW, statement, issues)


def test_statement_round_trip_and_duplicates(statement_store):
    stored = _stored()
    assert statement_store.add(stored) is True
    assert statement_store.add(stored) is False  # same user, same statement: stored once
    assert statement_store.get("camila", "stmt_1") == stored
    assert statement_store.for_user("camila") == (stored,)


def test_card_statement_round_trip_keeps_kinds_cuotas_and_obligations(statement_store):
    from dataclasses import replace
    from decimal import Decimal

    from neural_ledger.domain.ledger.entities import AccountType
    from neural_ledger.domain.shared.month import Month
    from neural_ledger.domain.statements.model import (
        CardObligations,
        Installment,
        LineKind,
        ScheduledAmount,
        SectionTotal,
        StatementSummary,
    )

    base = _stored("stmt_card")
    line = replace(
        base.statement.lines[0],
        kind=LineKind.PURCHASE,
        section="E",
        installment=Installment(2, 3, 30_000, Decimal("0.0345"), date(2026, 6, 15)),
    )
    statement = replace(
        base.statement,
        lines=(line, replace(base.statement.lines[1], kind=LineKind.PAYMENT, section="B")),
        summary=StatementSummary(-100_000, None, None, -45_442),
        account_type=AccountType.CREDIT_CARD,
        provisional=True,
        section_totals=(SectionTotal("B", 163_521), SectionTotal("E", -3_280)),
        obligations=CardObligations(45_442, 5_000, date(2026, 9, 15), 500_000, 300_000, 200_000, (ScheduledAmount(Month(2026, 9), 27_633),)),
    )
    stored = replace(base, statement=statement)
    assert statement_store.add(stored) is True
    assert statement_store.get("camila", "stmt_card") == stored


def test_statements_are_scoped_to_their_user(statement_store):
    statement_store.add(_stored())
    assert statement_store.get("diego", "stmt_1") is None
    assert statement_store.for_user("diego") == ()
    assert statement_store.add(_stored(user_id="diego")) is True  # another user's copy is theirs


@pytest.fixture(params=["memory", "sqlite"])
def transaction_store(request, tmp_path):
    from neural_ledger.adapters.outbound.persistence.memory import InMemoryTransactionStore
    from neural_ledger.adapters.outbound.persistence.sqlite import SqliteTransactionStore

    if request.param == "memory":
        return InMemoryTransactionStore()
    return SqliteTransactionStore(SqliteDatabase(tmp_path / "test.db"), TEST_CIPHER)


def _posted(user_id: str = "camila"):
    from dataclasses import replace

    from neural_ledger.domain.ledger.categorization import CategoryGuess, post_statement

    stored = replace(_stored(user_id=user_id), issues=())
    return post_statement(stored, {0: CategoryGuess("shopping", 0.734512)}, "naive_bayes@abc")


def test_transaction_round_trip_and_duplicates(transaction_store):
    posted = _posted()
    assert transaction_store.add(posted) == 2
    assert transaction_store.add(posted) == 0  # same transactions: stored once
    assert transaction_store.add(()) == 0
    assert transaction_store.for_user("camila") == posted


def test_card_transactions_round_trip_with_their_cuota_plan(transaction_store):
    from dataclasses import replace
    from decimal import Decimal

    from neural_ledger.domain.ledger.categorization import post_statement
    from neural_ledger.domain.ledger.entities import AccountType
    from neural_ledger.domain.statements.model import Installment, LineKind

    stored = replace(_stored(user_id="camila"), issues=())
    lines = (
        replace(stored.statement.lines[0], kind=LineKind.PURCHASE, installment=Installment(2, 3, 30_000, Decimal("0.0345"), date(2026, 6, 15))),
        replace(stored.statement.lines[1], kind=LineKind.PAYMENT),
    )
    card = replace(stored, statement=replace(stored.statement, lines=lines, account_type=AccountType.CREDIT_CARD))
    posted = post_statement(card, {}, "naive_bayes@abc")
    assert transaction_store.add(posted) == 2
    assert transaction_store.for_user("camila") == posted
    assert posted[0].transaction.installment is not None


def test_transactions_are_scoped_to_their_user_and_ordered_by_date(transaction_store):
    posted = _posted()
    transaction_store.add(tuple(reversed(posted)))
    assert transaction_store.for_user("camila") == posted  # 2026-09-02 before 2026-09-04
    assert transaction_store.for_user("diego") == ()
    assert transaction_store.add(_posted(user_id="diego")) == 2


def test_transactions_survive_a_restart(tmp_path):
    from neural_ledger.adapters.outbound.persistence.sqlite import SqliteTransactionStore

    path = tmp_path / "ledger.db"
    db = SqliteDatabase(path)
    SqliteTransactionStore(db, TEST_CIPHER).add(_posted())
    db.connection.close()
    assert SqliteTransactionStore(SqliteDatabase(path), TEST_CIPHER).for_user("camila") == _posted()
