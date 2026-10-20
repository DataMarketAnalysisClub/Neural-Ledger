"""A copy of everything stored about one user (G02, Ley 21.719 arts. 5, access, and 9, portability).

HTTP only: the agent has no tool for it, since the copy holds personal data the copilot never needs. It reads the
same stores the account deletion empties, so what can be downloaded is what a deletion erases, savings-rule proposals
(every status) and their authorizations included; of the investment syncs only the latest is in the copy
(tests/security/test_data_export.py maps every erased table to its section, or to the reason it has none).
Never in the copy: the password hash, session tokens, connection secrets, the investment access token and an
authorization's signature (action_hash: the HMAC of its terms is not the secret, but like every other outbound view it
never leaves the server, and the terms it covers are in the copy). Memory (ADR-048) is in the copy with or without
consent, like its own export: the consent and its counters, and every declaration version; a pending memory proposal is
not (the port has no list, and it expires within PP_0_1.proposal_ttl_seconds).
"""

from __future__ import annotations

from typing import Any

from ...domain.audit.events import Actor, AuditDraft, AuditKind
from ...domain.shared.serialization import to_primitive
from ..ports import (
    ActionRepository,
    AuditLog,
    Clock,
    ConnectionStore,
    IdGenerator,
    InvestmentStore,
    ReceiptStore,
    SandboxBank,
    StatementStore,
    TransactionStore,
    UserAccountStore,
    UserProfileStore,
)
from .memory import MemoryUseCases

EXPORT_FORMAT = "neural-ledger-export-3"  # bump when a section is added, renamed or changes shape


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
        investments: InvestmentStore,
        actions: ActionRepository,
        audit: AuditLog,
        clock: Clock,
        ids: IdGenerator,
        memory: MemoryUseCases | None = None,
    ) -> None:
        self._accounts = accounts
        self._profiles = profiles
        self._statements = statements
        self._transactions = transactions
        self._receipts = receipts
        self._connections = connections
        self._bank = bank
        self._investments = investments
        self._actions = actions
        self._audit = audit
        self._clock = clock
        self._ids = ids
        self._memory = memory

    def export(self, user_id: str, session_ref: str) -> dict[str, Any]:
        """The caller's data as JSON-ready primitives. The export is audited first, so the copy includes its own event."""
        now = self._clock.now()
        self._audit.append(AuditDraft(
            event_id=self._ids.new("evt"), timestamp=now, session_id=session_ref,
            user_id=user_id, actor=Actor.USER, kind=AuditKind.DATA_EXPORTED,
        ))
        account = self._accounts.get(user_id)  # None for a demo persona: it has no account
        connections = self._connections.for_user(user_id)
        link = self._investments.link(user_id)
        proposals, authorizations = self._actions.for_user(user_id)
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
            "proposals": to_primitive(proposals),
            "authorizations": [{k: v for k, v in to_primitive(a).items() if k != "action_hash"} for a in authorizations],
            "investments": {
                "link": None if link is None else {k: v for k, v in to_primitive(link).items() if k != "token"},
                "latest_snapshot": to_primitive(self._investments.latest(user_id)),
                "documents": to_primitive(self._investments.documents(user_id)),
            },
            "memory": self._memory_section(user_id),
            "audit_events": [to_primitive(e.to_record()) for e in self._audit.events() if e.draft.user_id == user_id],
        }

    def _memory_section(self, user_id: str) -> dict[str, Any] | None:
        if self._memory is None:
            return None
        state = self._memory.consent(user_id)
        return {
            "consent": {"consent": state.consent.value, "consent_generation": state.consent_generation, "memory_revision": state.memory_revision},
            "declarations": self._memory.export(user_id),
        }
