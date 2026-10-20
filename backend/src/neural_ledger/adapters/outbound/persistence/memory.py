"""In-memory adapters: default for tests and the offline demo. Thread-safe where it matters."""

from __future__ import annotations

import threading
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime

from ....application.conversation import Entry
from ....application.ports import ErasureReport, IdCollision, UserProfileStore
from ....domain.actions.terms import Authorization, Proposal, SavingsRule
from ....domain.audit.events import ERASURE_KINDS, GENESIS_HASH, AuditDraft, AuditEvent, erasure_detail, seal, tombstone
from ....domain.investments.documents import MAX_DOCUMENTS, StoredInvestmentDocument
from ....domain.investments.model import MAX_SNAPSHOTS, InvestmentLink, InvestmentSnapshot
from ....domain.ledger.categorization import PostedTransaction
from ....domain.receipts.model import StoredReceipt
from ....domain.statements.model import StoredStatement
from ....domain.user.account import Session, UserAccount
from ....domain.user.profile import UserProfile
from .overlay import PersonaOverlayProfileStore


class InMemorySavingsRuleStore:
    """Rules created by the simulated sandbox bank. Lost on restart; use the SQLite store for durable runs."""

    def __init__(self) -> None:
        self._rules: list[SavingsRule] = []
        self._lock = threading.Lock()

    def add(self, rule: SavingsRule) -> None:
        with self._lock:
            self._rules.append(rule)

    def count(self) -> int:
        return len(self._rules)

    def next_number(self) -> int:
        with self._lock:
            numbers = [int(r.rule_id[5:]) for r in self._rules if r.rule_id.startswith("rule_") and r.rule_id[5:].isdigit()]
        return max(numbers, default=0) + 1

    def for_user(self, user_id: str) -> tuple[SavingsRule, ...]:
        return tuple(r for r in self._rules if r.user_id == user_id)


class InMemoryStatementStore:
    def __init__(self) -> None:
        self._statements: dict[tuple[str, str], StoredStatement] = {}
        self._lock = threading.Lock()

    def add(self, stored: StoredStatement) -> bool:
        key = (stored.user_id, stored.statement_id)
        with self._lock:
            if key in self._statements:
                return False
            self._statements[key] = stored
            return True

    def get(self, user_id: str, statement_id: str) -> StoredStatement | None:
        return self._statements.get((user_id, statement_id))

    def for_user(self, user_id: str) -> tuple[StoredStatement, ...]:
        return tuple(s for (owner, _), s in self._statements.items() if owner == user_id)


class InMemoryReceiptStore:
    def __init__(self) -> None:
        self._receipts: dict[tuple[str, str], StoredReceipt] = {}
        self._lock = threading.Lock()

    def add(self, receipt: StoredReceipt) -> bool:
        key = (receipt.user_id, receipt.receipt_id)
        with self._lock:
            if key in self._receipts:
                return False
            self._receipts[key] = receipt
            return True

    def get(self, user_id: str, receipt_id: str) -> StoredReceipt | None:
        return self._receipts.get((user_id, receipt_id))

    def for_user(self, user_id: str) -> tuple[StoredReceipt, ...]:
        return tuple(r for (owner, _), r in self._receipts.items() if owner == user_id)

    def replace(self, receipt: StoredReceipt) -> bool:
        key = (receipt.user_id, receipt.receipt_id)
        with self._lock:
            if key not in self._receipts:
                return False
            self._receipts[key] = receipt
            return True


class InMemoryTransactionStore:
    def __init__(self) -> None:
        self._transactions: dict[tuple[str, str], PostedTransaction] = {}
        self._lock = threading.Lock()

    def add(self, posted: Sequence[PostedTransaction]) -> int:
        new = 0
        with self._lock:
            for p in posted:
                key = (p.user_id, p.transaction.txn_id)
                if key not in self._transactions:
                    self._transactions[key] = p
                    new += 1
        return new

    def for_user(self, user_id: str) -> tuple[PostedTransaction, ...]:
        mine = [p for (owner, _), p in self._transactions.items() if owner == user_id]
        return tuple(sorted(mine, key=lambda p: (p.transaction.date, p.statement_id, p.line_index)))

    def get(self, user_id: str, txn_id: str) -> PostedTransaction | None:
        return self._transactions.get((user_id, txn_id))

    def has_transactions(self, user_id: str) -> bool:
        with self._lock:
            return any(owner == user_id for owner, _ in self._transactions)



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
        self._lock = threading.RLock()

    def append(self, draft: AuditDraft) -> AuditEvent:
        with self._lock:
            prev = self._events[-1].event_hash if self._events else GENESIS_HASH
            event = seal(draft, len(self._events) + 1, prev)
            self._events.append(event)
            return event

    def append_all(self, drafts: Sequence[AuditDraft]) -> tuple[AuditEvent, ...]:
        with self._lock:
            previous = self._events[-1].event_hash if self._events else GENESIS_HASH
            sealed: list[AuditEvent] = []
            for draft in drafts:
                event = seal(draft, len(self._events) + len(sealed) + 1, previous)
                sealed.append(event)
                previous = event.event_hash
            self._events.extend(sealed)
            return tuple(sealed)

    def events(self, session_id: str | None = None) -> tuple[AuditEvent, ...]:
        with self._lock:
            return tuple(e for e in self._events if session_id is None or e.draft.session_id == session_id)


class InMemorySnapshotStore:
    def __init__(self) -> None:
        self._items: dict[tuple[str, str], object] = {}

    def put(self, snapshot_id: str, user_id: str, value: object) -> None:
        self._items[(snapshot_id, user_id)] = value

    def get(self, snapshot_id: str, user_id: str) -> object | None:
        return self._items.get((snapshot_id, user_id))

    def forget(self, user_id: str) -> int:
        mine = [key for key in self._items if key[1] == user_id]
        for key in mine:
            self._items.pop(key, None)
        return len(mine)


class InMemoryUserProfileStore:
    def __init__(self, profiles: Sequence[UserProfile] = ()) -> None:
        self._profiles = {p.user_id: p for p in profiles}
        self._lock = threading.RLock()

    def get(self, user_id: str) -> UserProfile | None:
        with self._lock:
            return self._profiles.get(user_id)

    def put(self, profile: UserProfile) -> None:
        with self._lock:
            self._profiles[profile.user_id] = profile


class InMemoryConversationStore:
    def __init__(self) -> None:
        self._sessions: dict[tuple[str, str], list[Entry]] = defaultdict(list)
        self._lock = threading.Lock()

    def history(self, user_id: str, session_id: str) -> tuple[Entry, ...]:
        with self._lock:
            return tuple(self._sessions.get((user_id, session_id), ()))

    def append(self, user_id: str, session_id: str, entries: Sequence[Entry], keep_last: int) -> None:
        with self._lock:
            items = self._sessions[(user_id, session_id)]
            items.extend(entries)
            if len(items) > keep_last:
                del items[: len(items) - keep_last]

    def forget(self, user_id: str) -> int:
        with self._lock:
            mine = [key for key in self._sessions if key[0] == user_id]
            for key in mine:
                del self._sessions[key]
            return len(mine)


class InMemoryUserAccountStore:
    def __init__(self) -> None:
        self._accounts: dict[str, UserAccount] = {}
        self._by_email: dict[str, str] = {}
        self._lock = threading.RLock()

    def add(self, account: UserAccount) -> bool:
        with self._lock:
            if account.user_id in self._accounts or account.email in self._by_email:
                return False
            self._accounts[account.user_id] = account
            self._by_email[account.email] = account.user_id
            return True

    def get(self, user_id: str) -> UserAccount | None:
        with self._lock:
            return self._accounts.get(user_id)

    def by_email(self, email: str) -> UserAccount | None:
        with self._lock:
            user_id = self._by_email.get(email)
            return self._accounts.get(user_id) if user_id is not None else None

    def set_sample_data(self, user_id: str, enabled: bool) -> bool:
        with self._lock:
            current = self._accounts.get(user_id)
            if current is None:
                return False
            self._accounts[user_id] = replace(current, sample_data=enabled)
            return True


class InMemorySessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}  # by token digest; the token itself is never held
        self._digest_of: dict[str, str] = {}
        self._lock = threading.RLock()

    def add(self, session: Session) -> None:
        with self._lock:
            if session.token_hash in self._sessions or session.session_ref in self._digest_of:
                raise ValueError("duplicate session")
            self._sessions[session.token_hash] = session
            self._digest_of[session.session_ref] = session.token_hash

    def by_token_hash(self, token_hash: str) -> Session | None:
        with self._lock:
            return self._sessions.get(token_hash)

    def contains(self, session_ref: str, token_hash: str) -> bool:
        with self._lock:
            return session_ref in self._digest_of or token_hash in self._sessions

    def revoke(self, session_ref: str, at: datetime) -> bool:
        with self._lock:
            digest = self._digest_of.get(session_ref)
            current = self._sessions.get(digest) if digest is not None else None
            if current is None or current.revoked_at is not None:
                return False
            self._sessions[digest] = replace(current, revoked_at=at)
            return True


class InMemoryTransactionWrites:
    """A transaction change and its audit events, both or neither: the events are sealed before the row changes."""

    def __init__(self, transactions: InMemoryTransactionStore, audit: InMemoryAuditLog) -> None:
        self._transactions = transactions
        self._audit = audit

    def update_transaction(self, expected: PostedTransaction, updated: PostedTransaction, events: Sequence[AuditDraft]) -> bool:
        _check_transaction_change(expected, updated, events)
        key = (expected.user_id, expected.transaction.txn_id)
        with self._audit._lock, self._transactions._lock:
            if self._transactions._transactions.get(key) != expected:
                return False
            existing = {event.draft.event_id for event in self._audit._events}
            ids = [event.event_id for event in events]
            if len(set(ids)) != len(ids) or existing.intersection(ids):
                raise IdCollision("generated identifier collision")
            self._audit.append_all(events)
            self._transactions._transactions[key] = updated
            return True


def _check_transaction_change(expected: PostedTransaction, updated: PostedTransaction, events: Sequence[AuditDraft]) -> None:
    owner = expected.user_id
    if (owner, expected.transaction.txn_id) != (updated.user_id, updated.transaction.txn_id) or any(e.user_id != owner for e in events):
        raise ValueError("transaction ownership mismatch")


def _check_investment_write(
    expected: InvestmentLink | None, link: InvestmentLink, snapshot: InvestmentSnapshot | None, events: Sequence[AuditDraft]
) -> None:
    owner = link.user_id
    if (expected is not None and expected.user_id != owner) or (snapshot is not None and snapshot.user_id != owner) or any(e.user_id != owner for e in events):
        raise ValueError("investment ownership mismatch")


class InMemoryInvestmentStore:
    """Investment links, synced snapshots and imported documents (ADR-044). A write and its audit events land together
    or not at all."""

    def __init__(self, audit: InMemoryAuditLog) -> None:
        self._audit = audit
        self._lock = threading.Lock()
        self._links: dict[str, InvestmentLink] = {}
        self._snapshots: dict[str, list[InvestmentSnapshot]] = {}
        self._documents: dict[str, list[StoredInvestmentDocument]] = {}

    def link(self, user_id: str) -> InvestmentLink | None:
        with self._lock:
            return self._links.get(user_id)

    def latest(self, user_id: str) -> InvestmentSnapshot | None:
        with self._lock:
            snapshots = self._snapshots.get(user_id)
            return snapshots[-1] if snapshots else None

    def save(
        self, expected: InvestmentLink | None, link: InvestmentLink, snapshot: InvestmentSnapshot | None, events: Sequence[AuditDraft]
    ) -> bool:
        _check_investment_write(expected, link, snapshot, events)
        with self._audit._lock, self._lock:
            if self._links.get(link.user_id) != expected:
                return False
            self._publish(events)
            self._links[link.user_id] = link
            if snapshot is not None:
                self._snapshots[link.user_id] = [*self._snapshots.get(link.user_id, []), snapshot][-MAX_SNAPSHOTS:]
            return True

    def remove(self, user_id: str, events: Sequence[AuditDraft]) -> int:
        if any(e.user_id != user_id for e in events):
            raise ValueError("investment ownership mismatch")
        with self._audit._lock, self._lock:
            if user_id not in self._links:
                return 0
            self._publish(events)
            del self._links[user_id]
            return 1 + len(self._snapshots.pop(user_id, []))

    def add_document(self, document: StoredInvestmentDocument, events: Sequence[AuditDraft]) -> bool:
        if any(e.user_id != document.user_id for e in events):
            raise ValueError("investment ownership mismatch")
        with self._audit._lock, self._lock:
            kept = self._documents.get(document.user_id, [])
            if any(d.document_id == document.document_id for d in kept):
                return False
            self._publish(events)
            self._documents[document.user_id] = [*kept, document][-MAX_DOCUMENTS:]
            return True

    def documents(self, user_id: str) -> tuple[StoredInvestmentDocument, ...]:
        with self._lock:
            return tuple(self._documents.get(user_id, ()))

    def remove_documents(self, user_id: str, events: Sequence[AuditDraft]) -> int:
        if any(e.user_id != user_id for e in events):
            raise ValueError("investment ownership mismatch")
        with self._audit._lock, self._lock:
            if not self._documents.get(user_id):
                return 0
            self._publish(events)
            return len(self._documents.pop(user_id))

    def drop(self, user_id: str) -> dict[str, int]:
        """Every row of the user, per table name of the SQLite adapter. The caller holds the lock (account erasure)."""
        links = int(self._links.pop(user_id, None) is not None)
        return {
            "investment_links": links,
            "investment_snapshots": len(self._snapshots.pop(user_id, [])),
            "investment_documents": len(self._documents.pop(user_id, [])),
        }

    def _publish(self, events: Sequence[AuditDraft]) -> None:
        existing = {event.draft.event_id for event in self._audit._events}
        ids = [event.event_id for event in events]
        if len(set(ids)) != len(ids) or existing.intersection(ids):
            raise IdCollision("generated identifier collision")
        self._audit.append_all(events)


class InMemoryAccountWrites:
    def __init__(
        self, accounts: InMemoryUserAccountStore, sessions: InMemorySessionStore,
        profiles: UserProfileStore, audit: InMemoryAuditLog,
    ) -> None:
        self._accounts = accounts
        self._sessions = sessions
        self._profiles = profiles
        self._audit = audit
        self._profile_store = profiles._inner if isinstance(profiles, PersonaOverlayProfileStore) else profiles
        sessions._lock = accounts._lock
        audit._lock = accounts._lock
        self._profile_store._lock = accounts._lock

    def _publish(self, events: Sequence[AuditDraft], action) -> None:
        accounts = self._accounts._accounts.copy()
        emails = self._accounts._by_email.copy()
        sessions = self._sessions._sessions.copy()
        refs = self._sessions._digest_of.copy()
        profiles = self._profile_store._profiles.copy()
        audit = self._audit._events.copy()
        try:
            action()
            self._audit.append_all(events)
        except BaseException:
            self._accounts._accounts = accounts
            self._accounts._by_email = emails
            self._sessions._sessions = sessions
            self._sessions._digest_of = refs
            self._profile_store._profiles = profiles
            self._audit._events = audit
            raise

    def _check_events(self, events: Sequence[AuditDraft]) -> None:
        existing = {event.draft.event_id for event in self._audit._events}
        ids = [event.event_id for event in events]
        if len(set(ids)) != len(ids) or existing.intersection(ids):
            raise IdCollision("generated identifier collision")

    def register(self, account: UserAccount, profile: UserProfile, session: Session, events: Sequence[AuditDraft]) -> bool:
        if profile.user_id != account.user_id or session.user_id != account.user_id or any(
            event.user_id != account.user_id for event in events
        ):
            raise ValueError("account ownership mismatch")
        with self._accounts._lock:
            if self._accounts.by_email(account.email) is not None:
                return False
            if self._accounts.get(account.user_id) is not None or self._profiles.get(account.user_id) is not None:
                raise IdCollision("generated identifier collision")
            if self._sessions.contains(session.session_ref, session.token_hash):
                raise IdCollision("generated identifier collision")
            self._check_events(events)

            def insert() -> None:
                self._profiles.put(profile)
                if not self._accounts.add(account):
                    raise IdCollision("generated identifier collision")
                self._sessions.add(session)

            self._publish(events, insert)
            return True

    def open_session(self, session: Session, events: Sequence[AuditDraft]) -> None:
        with self._accounts._lock:
            if self._sessions.contains(session.session_ref, session.token_hash):
                raise IdCollision("generated identifier collision")
            self._check_events(events)
            self._publish(events, lambda: self._sessions.add(session))

    def close_session(self, session: Session, at: datetime, events: Sequence[AuditDraft]) -> bool:
        with self._accounts._lock:
            current = self._sessions.by_token_hash(session.token_hash)
            if current is None or current.session_ref != session.session_ref or current.revoked_at is not None:
                return False
            self._check_events(events)

            def revoke() -> None:
                if not self._sessions.revoke(session.session_ref, at):
                    raise RuntimeError("session changed during account write")

            self._publish(events, revoke)
            return True

    def set_sample_data(self, user_id: str, enabled: bool, events: Sequence[AuditDraft]) -> bool:
        with self._accounts._lock:
            if self._accounts.get(user_id) is None:
                return False
            self._check_events(events)

            def update() -> None:
                if not self._accounts.set_sample_data(user_id, enabled):
                    raise RuntimeError("account changed during account write")

            self._publish(events, update)
            return True

    def update_profile(self, expected: UserProfile, updated: UserProfile, events: Sequence[AuditDraft]) -> bool:
        if updated.user_id != expected.user_id or any(event.user_id != expected.user_id for event in events):
            raise ValueError("profile ownership mismatch")
        with self._accounts._lock:
            # The writable store only: a persona behind the overlay is never there, so it never matches.
            if self._profile_store.get(expected.user_id) != expected:
                return False
            self._check_events(events)
            self._publish(events, lambda: self._profile_store.put(updated))
            return True


class InMemoryAccountErasure:
    """Account deletion over the in-memory stores: every lock held, so no write lands halfway through."""

    def __init__(
        self, accounts: InMemoryUserAccountStore | None, sessions: InMemorySessionStore | None, profiles: UserProfileStore,
        audit: InMemoryAuditLog, statements: InMemoryStatementStore, transactions: InMemoryTransactionStore,
        rules: InMemorySavingsRuleStore, actions: InMemoryActionRepository, receipts: InMemoryReceiptStore | None = None,
        investments: InMemoryInvestmentStore | None = None,
    ) -> None:
        self._accounts, self._sessions, self._audit = accounts, sessions, audit
        self._profiles = profiles._inner if isinstance(profiles, PersonaOverlayProfileStore) else profiles
        self._statements, self._transactions, self._rules, self._actions = statements, transactions, rules, actions
        self._receipts = receipts or InMemoryReceiptStore()
        self._investments = investments or InMemoryInvestmentStore(audit)

    def erase(self, user_id: str, *, keep_account: bool, event: AuditDraft) -> ErasureReport:
        with (
            self._audit._lock, self._statements._lock, self._transactions._lock, self._receipts._lock, self._rules._lock,
            self._actions._lock, self._investments._lock,
        ):
            if event.event_id in {e.draft.event_id for e in self._audit._events}:
                raise IdCollision("generated identifier collision")
            counts = {
                "statements": _drop(self._statements._statements, lambda key, _: key[0] == user_id),
                "transactions": _drop(self._transactions._transactions, lambda key, _: key[0] == user_id),
                "receipts": _drop(self._receipts._receipts, lambda key, _: key[0] == user_id),
                "proposals": _drop(self._actions._proposals, lambda _, p: p.user_id == user_id),
                "authorizations": _drop(self._actions._authorizations, lambda _, a: a.user_id == user_id),
                **self._investments.drop(user_id),
            }
            kept = [r for r in self._rules._rules if r.user_id != user_id]
            counts["savings_rules"], self._rules._rules = len(self._rules._rules) - len(kept), kept
            if not keep_account:
                counts.update(self._drop_account(user_id))
            erased = [e.sequence for e in self._audit._events if e.draft.user_id == user_id and e.draft.kind not in ERASURE_KINDS]
            self._audit._events = [
                tombstone(e, event.event_id, event.timestamp) if e.sequence in set(erased) else e for e in self._audit._events
            ]
            self._audit.append(replace(event, detail=erasure_detail(erased, counts)))
            return ErasureReport(counts, len(erased))

    def _drop_account(self, user_id: str) -> dict[str, int]:
        counts = {"sessions": 0, "user_profiles": 0, "user_accounts": 0}
        if self._sessions is not None:
            with self._sessions._lock:
                digests = [d for d, s in self._sessions._sessions.items() if s.user_id == user_id]
                for digest in digests:
                    session = self._sessions._sessions.pop(digest)
                    self._sessions._digest_of.pop(session.session_ref, None)
                counts["sessions"] = len(digests)
        with self._profiles._lock:
            counts["user_profiles"] = int(self._profiles._profiles.pop(user_id, None) is not None)
        if self._accounts is not None:
            with self._accounts._lock:
                account = self._accounts._accounts.pop(user_id, None)
                if account is not None:
                    self._accounts._by_email.pop(account.email, None)
                counts["user_accounts"] = int(account is not None)
        return counts


def _drop(items: dict, doomed) -> int:
    keys = [key for key, value in items.items() if doomed(key, value)]
    for key in keys:
        del items[key]
    return len(keys)
