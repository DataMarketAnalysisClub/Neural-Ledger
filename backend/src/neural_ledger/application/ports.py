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
from ..domain.ledger.categorization import CategoryGuess
from ..domain.statements.model import BankStatement, StoredStatement
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


class NotFound(Exception):
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
    """Turns a statement file (PDF or image bytes) into a BankStatement. Never decides whether it adds up."""

    def read(self, content: bytes) -> BankStatement: ...


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


@runtime_checkable
class ConversationStore(Protocol):
    def history(self, session_id: str) -> tuple[Entry, ...]: ...

    def append(self, session_id: str, entries: Sequence[Entry], keep_last: int) -> None: ...


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
