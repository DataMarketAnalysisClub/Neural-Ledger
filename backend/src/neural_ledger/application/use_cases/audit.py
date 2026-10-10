"""Audit queries and chain verification (Role C). Export to files is an adapter concern (CLI)."""

from __future__ import annotations

from dataclasses import dataclass

from ...domain.audit.events import AuditEvent, ChainCheck, verify_chain
from ..ports import AuditLog


@dataclass(frozen=True, slots=True)
class AuditPage:
    events: tuple[dict, ...]
    chain_ok: bool


class AuditUseCases:
    def __init__(self, audit: AuditLog) -> None:
        self._audit = audit

    def events(self, session_id: str | None = None, limit: int = 200) -> AuditPage:
        all_events = self._audit.events()
        selected = [e for e in all_events if session_id is None or e.draft.session_id == session_id]
        check = verify_chain(all_events)
        return AuditPage(tuple(e.to_record() for e in selected[-max(1, min(limit, 1000)) :]), check.ok)

    def verify(self) -> ChainCheck:
        return verify_chain(self._audit.events())

    def raw(self) -> tuple[AuditEvent, ...]:
        return self._audit.events()
