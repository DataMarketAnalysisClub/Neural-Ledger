"""ADR-048 §8: a statement import audits what it changes in the evidence for a declaration, durably, once.

Its statements, postings, STATEMENT_IMPORTED events and MEMORY_EVIDENCE_CHANGED events commit together; before and
after are derived with the same rules and date. Reading memory audits nothing, and neither does an import without the
memory consent. Memory is saved only: these imports change no financial number.
"""

from __future__ import annotations

import pytest

from neural_ledger.adapters.outbound.persistence.memory import InMemoryAuditLog
from neural_ledger.domain.audit.events import AuditKind
from neural_ledger.domain.ledger.categorization import MOVEMENT
from neural_ledger.domain.memory.catalog import Declaration, MemoryType, ProfileOrigin, SalaryNet, Source
from neural_ledger.domain.memory.salary_check import Status, check_salary, eligible_inputs
from neural_ledger.domain.shared.month import Month
from tests.application.test_memory_writes import World
from tests.statement_samples import santander_xlsx

SALARY = 1_200_000
# September: the salary credited on its payday (Wed 30/09), but the window runs to Mon 05/10, past the statement.
SEPTEMBER = santander_xlsx(
    movements=(
        ("02/09", "Sucursal Uno", "Compra Nacional VD SHOP ONE", "2432020", -900),
        ("30/09", "O.Gerencia", "0000000009 REMUNERACION EMPRESA", "", SALARY),
    ),
)
# October: no salary at all, only the coverage that makes September's payday eligible.
OCTOBER = santander_xlsx(movements=(("02/10", "Sucursal Uno", "Compra Nacional VD CAFE TWO", "2442020", -8_969),), period=("01/10/2026", "31/10/2026"))


@pytest.fixture(params=["memory", "sqlite"])
def world(request, tmp_path) -> World:
    return World(request.param, tmp_path)


def _transitions(world: World):
    return [e.draft for e in world.events(AuditKind.MEMORY_EVIDENCE_CHANGED)]


def _declared(world: World) -> World:
    world.grant(world.ana)
    assert world.declare(world.ana, amount=SALARY, month="2026-09").ok
    return world


def _import(world: World, content: bytes):
    result = world.services.statements.import_statement(world.ana, content)
    assert result.status.value == "OK", result
    return result


def _status(world: World) -> Status:
    statements = world.services.statements._store.for_user(world.ana)
    transactions = world.services.statements._transactions.for_user(world.ana)
    versions = world.store.chain_of_type(world.ana, MemoryType.SALARY_NET)
    return check_salary(versions, *eligible_inputs(world.ana, statements, transactions), world.clock.now().date()).status


def test_a_coverage_change_is_one_transition_with_codes_and_counts_only(world):
    _declared(world)
    _import(world, SEPTEMBER)
    assert _transitions(world) == []  # the payday is not eligible yet: still declared
    _import(world, OCTOBER)
    (event,) = _transitions(world)
    assert event.user_id == world.ana and event.policy_version == "salary-check-0.1"
    assert event.detail.endswith("status=declared->verified matched=1 missed=0 checker=salary-check-0.1")
    assert str(SALARY) not in event.detail and "REMUNERACION" not in event.detail
    imported = [e for e in world.events(AuditKind.STATEMENT_IMPORTED) if e.draft.user_id == world.ana]
    assert imported[-1].sequence == event_sequence(world, event) - 1  # committed with its import, right after it
    assert world.services.audit.verify().ok


def event_sequence(world: World, draft) -> int:
    return next(e.sequence for e in world.adapters.audit_log.events() if e.draft.event_id == draft.event_id)


def test_identical_reimports_and_reads_never_repeat_a_transition(world):
    _declared(world)
    _import(world, SEPTEMBER)
    _import(world, OCTOBER)
    for content in (OCTOBER, SEPTEMBER, OCTOBER):
        assert _import(world, content).data.imports[0].duplicate
    world.store.for_user(world.ana)
    world.memory.declarations_in_use(world.ana)
    assert len(_transitions(world)) == 1


@pytest.mark.parametrize("consent", ["missing", "revoked"])
def test_without_consent_an_import_derives_nothing_from_memory(world, consent):
    if consent == "revoked":
        _declared(world)
        assert world.memory.set_consent(world.ana, "s_1", {"consent": "revoked"}).ok
    else:  # never granted: a declaration can only be there written straight to the store
        salary = Declaration(
            "mem_direct", "chn_direct", 1, world.ana, SalaryNet(SALARY, Month.parse("2026-09")), world.clock.now(), Source.PROFILE,
            ProfileOrigin(), "evt_direct",
        )
        assert world.store.append((salary,), 0)
    _import(world, SEPTEMBER)
    _import(world, OCTOBER)
    assert _transitions(world) == []


def test_another_users_import_audits_nothing_for_this_user(world):
    _declared(world)
    for content in (SEPTEMBER, OCTOBER):
        assert world.services.statements.import_statement(world.bea, content).status.value == "OK"
    assert _transitions(world) == []


def test_an_import_that_fails_at_its_commit_stores_nothing_and_loses_no_transition(world, monkeypatch):
    _declared(world)
    _import(world, SEPTEMBER)
    before = (world.services.statements._store.for_user(world.ana), world.services.statements._transactions.for_user(world.ana), world.adapters.audit_log.events())
    if world.persistence == "sqlite":
        db = world.store._db
        db.connection.execute("CREATE TEMP TRIGGER crash AFTER INSERT ON main.audit_events BEGIN SELECT RAISE(ABORT, 'injected crash'); END")
        with pytest.raises(Exception, match="injected crash"):
            world.services.statements.import_statement(world.ana, OCTOBER)
        db.connection.execute("DROP TRIGGER crash")
    else:
        def crash(*_args, **_kwargs):
            raise RuntimeError("injected crash")

        monkeypatch.setattr(InMemoryAuditLog, "append_all", crash)
        with pytest.raises(RuntimeError, match="injected crash"):
            world.services.statements.import_statement(world.ana, OCTOBER)
        monkeypatch.undo()
    after = (world.services.statements._store.for_user(world.ana), world.services.statements._transactions.for_user(world.ana), world.adapters.audit_log.events())
    assert after == before  # no statement, no posting, no event: nothing half-imported
    _import(world, OCTOBER)  # the import again, after the crash
    assert [e.detail.split(" ", 1)[1] for e in _transitions(world)] == ["status=declared->verified matched=1 missed=0 checker=salary-check-0.1"]


def test_an_import_retries_when_the_data_changes_before_its_commit(world, monkeypatch):
    _declared(world)
    _import(world, SEPTEMBER)
    writes = world.services.statements._writes
    commit, calls = writes.commit, []

    def changed_meanwhile(user_id, token, statements, transactions, events):
        calls.append(len(events))
        if len(calls) == 1:  # a new version is confirmed between this attempt's reads and its commit
            assert world.declare(world.ana, amount=SALARY, month="2026-09", expected=1).ok
        return commit(user_id, token, statements, transactions, events)

    monkeypatch.setattr(writes, "commit", changed_meanwhile)
    _import(world, OCTOBER)
    assert len(calls) == 2  # the first commit refused, the second prepared again with the new chain
    (event,) = _transitions(world)
    assert "status=declared->verified" in event.detail


def test_a_category_corrected_under_the_same_txn_id_changes_the_token_and_the_derived_status(world):
    _declared(world)
    _import(world, SEPTEMBER)
    _import(world, OCTOBER)
    assert _status(world) is Status.VERIFIED
    salary = next(p for p in world.services.statements._transactions.for_user(world.ana) if p.transaction.amount == SALARY)
    token = world.services.statements._writes.token(world.ana)
    assert world.services.ledger.set_category(world.ana, "s_1", salary.transaction.txn_id, MOVEMENT).status.value == "OK"
    assert world.services.statements._writes.token(world.ana) != token  # same txn_id, new content: a new fingerprint
    assert _status(world) is Status.DECLARED  # derived from the corrected content on every read, nothing stored
    assert len(_transitions(world)) == 1  # a correction is not an import: no event of its own


def test_the_token_covers_coverage_declarations_and_consent(world):
    token = lambda: world.services.statements._writes.token(world.ana)  # noqa: E731
    seen = {token()}
    world.grant(world.ana)
    seen.add(token())
    assert world.declare(world.ana, amount=SALARY, month="2026-09").ok
    seen.add(token())
    _import(world, OCTOBER)  # coverage only
    seen.add(token())
    assert len(seen) == 4
