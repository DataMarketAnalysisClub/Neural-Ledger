"""A copy of everything stored about one user (G02, Ley 21.719 arts. 5, access, and 9, portability).

HTTP only: the agent has no tool for it, since the copy holds personal data the copilot never needs. It reads the
same stores the account deletion empties, so what can be downloaded is what a deletion erases. Never in the copy:
the password hash, session tokens and connection secrets.
"""

from __future__ import annotations

from typing import Any

from ...domain.audit.events import Actor, AuditDraft, AuditKind
from ...domain.shared.serialization import to_primitive
from ..ports import (
    AuditLog,
    Clock,
    ConnectionStore,
    IdGenerator,
    ReceiptStore,
    SandboxBank,
    StatementStore,
    TransactionStore,
    UserAccountStore,
    UserProfileStore,
)

EXPORT_FORMAT = "neural-ledger-export-1"  # bump when a section is added, renamed or changes shape


class DataExport:
    def __init__(
        self,
        accounts: UserAccountStore,
        profiles: UserProfileStore,
        statements: StatementStore,
        transactions: TransactionStore,
        receipts: ReceiptStore,
        connections: ConnectionStore,
        bank: SandboxBank,
        audit: AuditLog,
        clock: Clock,
        ids: IdGenerator,
    ) -> None:
        self._accounts = accounts
        self._profiles = profiles
        self._statements = statements
        self._transactions = transactions
        self._receipts = receipts
        self._connections = connections
        self._bank = bank
        self._audit = audit
        self._clock = clock
        self._ids = ids

    def export(self, user_id: str, session_ref: str) -> dict[str, Any]:
        """The caller's data as JSON-ready primitives. The export is audited first, so the copy includes its own event."""
        now = self._clock.now()
        self._audit.append(AuditDraft(
            event_id=self._ids.new("evt"), timestamp=now, session_id=session_ref,
            user_id=user_id, actor=Actor.USER, kind=AuditKind.DATA_EXPORTED,
        ))
        account = self._accounts.get(user_id)  # None for a demo persona: it has no account
        connections = self._connections.for_user(user_id)
        return {
            "format": EXPORT_FORMAT,
            "exported_at": now.isoformat(),
            "user_id": user_id,
            "account": None if account is None else {
                "email": account.email, "created_at": account.created_at.isoformat(), "sample_data": account.sample_data,
            },
            "profile": to_primitive(self._profiles.get(user_id)),
            "statements": to_primitive(self._statements.for_user(user_id)),
            "transactions": to_primitive(self._transactions.for_user(user_id)),
            "receipts": to_primitive(self._receipts.for_user(user_id)),
            "connections": [
                {**to_primitive(c), "results": to_primitive(self._connections.results(user_id, c.connection_id))} for c in connections
            ],
            "savings_rules": to_primitive(self._bank.active_rules(user_id)),
            "audit_events": [to_primitive(e.to_record()) for e in self._audit.events() if e.draft.user_id == user_id],
        }
