"""What an import changed in the evidence for a declaration (ADR-048 §8): audited at import, never on read.

Before and after are both derived, with the same rules and the same reference date, from the inputs as they were
before the import and as they will be once it commits. A change of status (declared, verified, conflict) is a
transition; anything else is not. An identical re-import has identical inputs on both sides, so it never repeats a
transition, and since the import commits its statements, transactions and these events together, a crash loses none.
Nothing here is stored: the status stays derived on every read.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from ..audit.events import AuditDraft
from ..ledger.categorization import PostedTransaction
from ..statements.model import StoredStatement
from .catalog import Declaration
from .salary_check import CHECKER_VERSION, PROPOSED_RULES, SalaryRules, Status, check_salary, eligible_inputs


@dataclass(frozen=True, slots=True)
class EvidenceTransition:
    chain_id: str
    before: Status
    after: Status
    matched: int  # of the current version, after the import
    missed: int

    def detail(self) -> str:
        """Codes and counts only: no amount, no glosa, no statement text."""
        return (
            f"chain={self.chain_id} status={self.before.value}->{self.after.value} matched={self.matched} "
            f"missed={self.missed} checker={CHECKER_VERSION}"
        )


def evidence_transitions(
    user_id: str,
    declarations: Sequence[Declaration],
    before: tuple[Sequence[StoredStatement], Sequence[PostedTransaction]],
    after: tuple[Sequence[StoredStatement], Sequence[PostedTransaction]],
    today: date,
    rules: SalaryRules = PROPOSED_RULES,
) -> tuple[EvidenceTransition, ...]:
    """One transition per chain whose status the import changes. The caller passes no declarations without consent."""
    chains: dict[str, list[Declaration]] = {}
    for d in declarations:
        if d.user_id == user_id:
            chains.setdefault(d.chain_id, []).append(d)
    transitions = []
    for chain_id, versions in chains.items():
        old = check_salary(versions, *eligible_inputs(user_id, *before), today, rules)
        new = check_salary(versions, *eligible_inputs(user_id, *after), today, rules)
        if old.status is not new.status:
            transitions.append(EvidenceTransition(chain_id, old.status, new.status, new.matched, new.missed))
    return tuple(transitions)


def check_import_batch(
    user_id: str, statements: Sequence[StoredStatement], transactions: Sequence[PostedTransaction], events: Sequence[AuditDraft]
) -> None:
    """The batch every adapter's StatementImportWrites.commit refuses before it looks at any stored state."""
    if any(s.user_id != user_id for s in statements) or any(p.user_id != user_id for p in transactions) or any(
        e.user_id != user_id for e in events
    ):
        raise ValueError("import ownership mismatch")
    ids = [e.event_id for e in events]
    if len(set(ids)) != len(ids) or len({s.statement_id for s in statements}) != len(statements) or len(
        {p.transaction.txn_id for p in transactions}
    ) != len(transactions):
        raise ValueError("an id appears twice in the import")
