"""In-memory adapters: default for tests and the offline demo. Thread-safe where it matters."""

from __future__ import annotations

import threading
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime

from ....application.conversation import Entry
from ....domain.actions.terms import Authorization, Proposal
from ....domain.audit.events import GENESIS_HASH, AuditDraft, AuditEvent, seal
from ....domain.user.profile import UserProfile


class InMemoryActionRepository:
    def __init__(self) -> None:
        self._proposals: dict[str, Proposal] = {}
        self._authorizations: dict[str, Authorization] = {}
        self._lock = threading.Lock()

    def add_proposal(self, proposal: Proposal) -> None:
        with self._lock:
            self._proposals[proposal.proposal_id] = proposal

    def get_proposal(self, proposal_id: str) -> Proposal | None:
        return self._proposals.get(proposal_id)

    def update_proposal(self, proposal: Proposal) -> None:
        with self._lock:
            self._proposals[proposal.proposal_id] = proposal

    def add_authorization(self, authorization: Authorization) -> None:
        with self._lock:
            self._authorizations[authorization.authorization_id] = authorization

    def get_authorization(self, authorization_id: str) -> Authorization | None:
        return self._authorizations.get(authorization_id)

    def consume_authorization(self, authorization_id: str, at: datetime) -> bool:
        with self._lock:
            current = self._authorizations.get(authorization_id)
            if current is None or current.consumed_at is not None:
                return False
            self._authorizations[authorization_id] = replace(current, consumed_at=at)
            return True

    def for_session(self, session_id: str) -> tuple[tuple[Proposal, ...], tuple[Authorization, ...]]:
        return (
            tuple(p for p in self._proposals.values() if p.session_id == session_id),
            tuple(a for a in self._authorizations.values() if a.session_id == session_id),
        )

    # test hook for S05 (tampering with stored terms)
    def _tamper(self, authorization_id: str, **changes) -> None:
        a = self._authorizations[authorization_id]
        self._authorizations[authorization_id] = replace(a, terms=replace(a.terms, **changes))


class InMemoryAuditLog:
    def __init__(self) -> None:
        self._events: list[AuditEvent] = []
        self._lock = threading.Lock()

    def append(self, draft: AuditDraft) -> AuditEvent:
        with self._lock:
            prev = self._events[-1].event_hash if self._events else GENESIS_HASH
            event = seal(draft, len(self._events) + 1, prev)
            self._events.append(event)
            return event

    def events(self, session_id: str | None = None) -> tuple[AuditEvent, ...]:
        return tuple(e for e in self._events if session_id is None or e.draft.session_id == session_id)


class InMemorySnapshotStore:
    def __init__(self) -> None:
        self._items: dict[tuple[str, str], object] = {}

    def put(self, snapshot_id: str, user_id: str, value: object) -> None:
        self._items[(snapshot_id, user_id)] = value

    def get(self, snapshot_id: str, user_id: str) -> object | None:
        return self._items.get((snapshot_id, user_id))


class InMemoryUserProfileStore:
    def __init__(self, profiles: Sequence[UserProfile] = ()) -> None:
        self._profiles = {p.user_id: p for p in profiles}

    def get(self, user_id: str) -> UserProfile | None:
        return self._profiles.get(user_id)

    def put(self, profile: UserProfile) -> None:
        self._profiles[profile.user_id] = profile


class InMemoryConversationStore:
    def __init__(self) -> None:
        self._sessions: dict[str, list[Entry]] = defaultdict(list)
        self._lock = threading.Lock()

    def history(self, session_id: str) -> tuple[Entry, ...]:
        return tuple(self._sessions.get(session_id, ()))

    def append(self, session_id: str, entries: Sequence[Entry], keep_last: int) -> None:
        with self._lock:
            items = self._sessions[session_id]
            items.extend(entries)
            if len(items) > keep_last:
                del items[: len(items) - keep_last]
