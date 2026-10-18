"""Ports: the interfaces the application needs from the outside world.

Every port has at least one adapter that needs no network and no API key, so the whole
system runs and tests offline. Concrete adapters live in neural_ledger.adapters and are
wired only in neural_ledger.bootstrap.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Protocol, runtime_checkable

from ..domain.actions.terms import (
    ActionTerms,
    Authorization,
    ExecutionReceipt,
    Proposal,
    SavingsRule,
)
from ..domain.agent.questions import Judgment, Question
from ..domain.audit.events import AuditDraft, AuditEvent
from ..domain.finance.model import FinancialModel
from ..domain.ledger.categorization import CategoryGuess, PostedTransaction
from ..domain.privacy.redaction import Span
from ..domain.statements.model import BankStatement, StoredStatement
from ..domain.user.account import Session, UserAccount
from ..domain.user.profile import UserProfile
from .conversation import Entry, ModelRequest, ModelTurn


class PortUnavailable(Exception):
    """An external dependency could not answer. Callers fall back or fail closed."""


class DecisionModelUnavailable(PortUnavailable):
    pass


class LanguageModelUnavailable(PortUnavailable):
    pass


class StatementReaderUnavailable(PortUnavailable):
    """The reader lacks what this file needs (e.g. OCR for a scan). Not the file's fault."""


class ClassifierUnavailable(PortUnavailable):
    """The transaction classifier cannot run (e.g. the `ml` extra is missing). Statements are stored, not posted."""


class DetectorUnavailable(PortUnavailable):
    """The personal-data detector could not answer. The domain rules still redact; the import is flagged as degraded."""


class NotFound(Exception):
    pass


class ReadOnlyProfile(Exception):
    pass


class StatementUnreadable(Exception):
    """The file is not a statement of any known bank layout, or does not fit its layout."""


@runtime_checkable
class Clock(Protocol):
    def now(self) -> datetime: ...


@runtime_checkable
class IdGenerator(Protocol):
    def new(self, prefix: str) -> str: ...


@runtime_checkable
class Signer(Protocol):
    """Signs canonical action terms. The secret stays inside the adapter (HMAC now, KMS later)."""

    def sign(self, message: str) -> str: ...

    def verify(self, message: str, signature: str) -> bool: ...


@runtime_checkable
class FinancialModelSource(Protocol):
    """Where the estimated financial model comes from: persona fixtures or the sandbox ledger."""

    def load(self, user_id: str) -> FinancialModel: ...


@runtime_checkable
class StatementReader(Protocol):
    """Turns a statement file (spreadsheet, PDF or image bytes) into the statements it holds, in order.

    Usually one; a card statement can hold a national and an international one. Never decides
    whether they add up."""

    def read(self, content: bytes) -> tuple[BankStatement, ...]: ...


@runtime_checkable
class PersonalDataDetector(Protocol):
    """Finds personal data the domain rules miss (a name outside a transfer, an address), after them (ADR-028).

    Its spans can only add masking. It receives raw statement text: an adapter that sends it out of the process
    says so in docs/SECURITY.md, and never puts that text in an error or a log. Adding a detector takes one adapter
    class and one registry entry in bootstrap/container.py.
    """

    name: str  # reported with every import it redacts; "none" when the rules run alone

    def detect(self, texts: Sequence[str]) -> Sequence[Sequence[Span]]:
        """Spans per text, in the same order, with offsets into that text. Raise DetectorUnavailable on any error."""
        ...


@runtime_checkable
class StatementStore(Protocol):
    def add(self, stored: StoredStatement) -> bool:
        """Store unless this user already has this statement_id. Returns False for a duplicate."""
        ...

    def get(self, user_id: str, statement_id: str) -> StoredStatement | None: ...

    def for_user(self, user_id: str) -> tuple[StoredStatement, ...]: ...


@runtime_checkable
class TransactionClassifier(Protocol):
    """Guesses a spending category per description. Its labels are gated by domain/ledger/categorization.

    Swap the method by registering another adapter in bootstrap; nothing else changes.
    """

    name: str  # recorded on every transaction it categorizes; change it when the method or its data change

    def classify(self, descriptions: Sequence[str]) -> Sequence[CategoryGuess]:
        """One guess per description, in the same order."""
        ...


@runtime_checkable
class TransactionStore(Protocol):
    """The transaction ledger built from imported statements, per user."""

    def add(self, posted: Sequence[PostedTransaction]) -> int:
        """Store the transactions this user does not have yet (by txn_id); existing ones keep their category.

        Returns how many were new.
        """
        ...

    def for_user(self, user_id: str) -> tuple[PostedTransaction, ...]:
        """Oldest first: by date, then statement line."""
        ...

    def get(self, user_id: str, txn_id: str) -> PostedTransaction | None:
        """This user's transaction, or None: another user's id is not found either."""
        ...


@runtime_checkable
class TransactionWrites(Protocol):
    """Commit a user's change to a transaction and its audit drafts together, or leave both unchanged (ADR-023)."""

    def update_transaction(self, expected: PostedTransaction, updated: PostedTransaction, events: Sequence[AuditDraft]) -> bool:
        """Compare-and-set. False, with no writes, if the transaction is missing or no longer equals expected.

        Raises ValueError if the two are not the same user's same transaction or an event belongs to another user,
        and IdCollision on a reused event id; any exception also leaves no writes.
        """
        ...


@runtime_checkable
class SnapshotStore(Protocol):
    """Computed results by snapshot id. Proposals take their amount from here, never from model text."""

    def put(self, snapshot_id: str, user_id: str, value: object) -> None: ...

    def get(self, snapshot_id: str, user_id: str) -> object | None: ...


@runtime_checkable
class ActionRepository(Protocol):
    def add_proposal(self, proposal: Proposal) -> None: ...

    def get_proposal(self, proposal_id: str) -> Proposal | None: ...

    def update_proposal(self, proposal: Proposal) -> None: ...

    def add_authorization(self, authorization: Authorization) -> None: ...

    def get_authorization(self, authorization_id: str) -> Authorization | None: ...

    def consume_authorization(self, authorization_id: str, at: datetime) -> bool:
        """Atomically mark as used. Returns False if it was already used (replay)."""
        ...

    def for_session(self, session_id: str) -> tuple[tuple[Proposal, ...], tuple[Authorization, ...]]: ...


@runtime_checkable
class AuditLog(Protocol):
    def append(self, draft: AuditDraft) -> AuditEvent:
        """Atomically seal the draft onto the hash chain and store it."""
        ...

    def events(self, session_id: str | None = None) -> tuple[AuditEvent, ...]: ...


@runtime_checkable
class SandboxBank(Protocol):
    def create_savings_rule(self, user_id: str, terms: ActionTerms, authorization_id: str, execution_id: str) -> ExecutionReceipt: ...

    def active_rules(self, user_id: str) -> tuple[SavingsRule, ...]: ...


@runtime_checkable
class UserProfileStore(Protocol):
    def get(self, user_id: str) -> UserProfile | None: ...

    def put(self, profile: UserProfile) -> None: ...


@runtime_checkable
class ConversationStore(Protocol):
    def history(self, user_id: str, session_id: str) -> tuple[Entry, ...]: ...

    def append(self, user_id: str, session_id: str, entries: Sequence[Entry], keep_last: int) -> None: ...


@runtime_checkable
class LanguageModel(Protocol):
    """Understands, converses, chooses read tools and writes explanations. Never authorizes."""

    name: str

    def respond(self, request: ModelRequest) -> ModelTurn: ...


@runtime_checkable
class DecisionModel(Protocol):
    """Answers closed questions about text with calibrated probabilities (Jev-shaped)."""

    name: str

    def judge(self, state: str, questions: Sequence[Question]) -> Mapping[str, Judgment]: ...


@runtime_checkable
class PasswordHasher(Protocol):
    """Hashes and checks passwords. Only the encoded hash is ever stored, never the password."""

    def hash(self, password: str) -> str: ...

    def verify(self, password: str, encoded: str | None) -> bool:
        """None (no such account) or a malformed hash does the same work as a real check and returns False."""
        ...


@runtime_checkable
class TokenGenerator(Protocol):
    """Unguessable session tokens. Only their digest is stored."""

    def new_token(self) -> str: ...


@runtime_checkable
class UserAccountStore(Protocol):
    def add(self, account: UserAccount) -> bool:
        """Store unless the user_id or the (normalized) email already exists, atomically. Returns False for a duplicate."""
        ...

    def get(self, user_id: str) -> UserAccount | None: ...

    def by_email(self, email: str) -> UserAccount | None: ...

    def set_sample_data(self, user_id: str, enabled: bool) -> bool:
        """Returns False if there is no account with this id."""
        ...


@runtime_checkable
class SessionStore(Protocol):
    def add(self, session: Session) -> None: ...

    def by_token_hash(self, token_hash: str) -> Session | None: ...

    def revoke(self, session_ref: str, at: datetime) -> bool:
        """Atomically mark as revoked. Returns False if unknown or already revoked."""
        ...


class IdCollision(Exception):
    """A generated identifier already exists; no account mutation was committed."""


@runtime_checkable
class AccountWrites(Protocol):
    """Commit account state and its audit drafts together, or leave both unchanged.

    False is a failed precondition with no writes; exceptions also leave no writes.
    """

    def register(self, account: UserAccount, profile: UserProfile, session: Session, events: Sequence[AuditDraft]) -> bool: ...

    def open_session(self, session: Session, events: Sequence[AuditDraft]) -> None: ...

    def close_session(self, session: Session, at: datetime, events: Sequence[AuditDraft]) -> bool: ...

    def set_sample_data(self, user_id: str, enabled: bool, events: Sequence[AuditDraft]) -> bool: ...


@runtime_checkable
class ProfileWrites(Protocol):
    """Commit a writable profile change and its audit drafts together, or leave both unchanged."""

    def update_profile(self, expected: UserProfile, updated: UserProfile, events: Sequence[AuditDraft]) -> bool:
        """Compare-and-set. False, with no writes, if the stored writable profile is missing or no longer equals expected.

        Personas are never writable. Raises ValueError on an owner mismatch and IdCollision on a reused event id;
        any exception also leaves no writes.
        """
        ...
