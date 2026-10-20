"""Ports: the interfaces the application needs from the outside world.

Every port has at least one adapter that needs no network and no API key, so the whole
system runs and tests offline. Concrete adapters live in neural_ledger.adapters and are
wired only in neural_ledger.bootstrap.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from ..domain.actions.terms import (
    ActionTerms,
    Authorization,
    ExecutionReceipt,
    Proposal,
    SavingsRule,
)
from ..domain.agent.questions import Judgment, Question
from ..domain.audit.events import AuditDraft, AuditEvent
from ..domain.connections.bank import BankAccount, BankMovement
from ..domain.connections.model import Connection, ConnectionSnapshot
from ..domain.education.concepts import Passage
from ..domain.finance.model import FinancialModel
from ..domain.investments.documents import ReadInvestmentDocument, StoredInvestmentDocument
from ..domain.investments.model import InvestmentLink, InvestmentSnapshot, ReportedGoal
from ..domain.ledger.categorization import CategoryGuess, PostedTransaction
from ..domain.memory.catalog import Declaration, MemoryType
from ..domain.memory.consent import Consent, MemoryState
from ..domain.memory.proposals import MemoryProposal, WriteOutcome
from ..domain.privacy.redaction import Span
from ..domain.receipts.model import ReadReceipt, StoredReceipt
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


class InvestmentProviderUnavailable(PortUnavailable):
    """The investment provider could not answer (network, HTTP 5xx, an unexpected response). Nothing is stored."""


class InvestmentAccessRejected(Exception):
    """The provider refused the email and password, or no longer accepts the stored access token."""


class KnowledgeBaseUnavailable(PortUnavailable):
    """The concept index cannot answer (e.g. the `rag` extra or its embedding model is missing). The fallback takes over."""


class ConnectorUnavailable(PortUnavailable):
    """A connected service did not answer usably (ADR-047). The message is a short code, never the service's text."""


class TargetRefused(Exception):
    """A connected service's address was refused before anything was sent (ADR-047). args[0] is a TargetBlock."""


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


@dataclass(frozen=True, slots=True)
class DocumentText:
    """What a document says before anyone decides what it is: enough to route it, nothing to trust."""

    format: str  # xlsx | pdf | image
    text: str  # the first page's text in reading order (empty for a spreadsheet, which is always a statement)


@runtime_checkable
class ReceiptReader(Protocol):
    """Reads documents dropped on the copilot: their text to route them, and a receipt's fields (ADR-039).

    Never decides whether a receipt may be trusted: that is domain/receipts `check`. Raises StatementUnreadable
    for a file it cannot read and StatementReaderUnavailable when an extra it needs (OCR) is missing.
    """

    name: str  # reported with every receipt it reads

    def peek(self, content: bytes) -> DocumentText: ...

    def read_receipt(self, content: bytes) -> ReadReceipt: ...


@runtime_checkable
class ReceiptStore(Protocol):
    def add(self, receipt: StoredReceipt) -> bool:
        """Store unless this user already has this receipt_id. Returns False for a duplicate."""
        ...

    def get(self, user_id: str, receipt_id: str) -> StoredReceipt | None: ...

    def for_user(self, user_id: str) -> tuple[StoredReceipt, ...]:
        """In import order."""
        ...

    def replace(self, receipt: StoredReceipt) -> bool:
        """Overwrite this user's stored receipt with the same id (a user correction). False if it is not stored."""
        ...


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


class ImportCommit(str, Enum):
    COMMITTED = "COMMITTED"
    CHANGED = "CHANGED"  # the data the import decided on moved: prepare again (bounded)
    OWNER_GONE = "OWNER_GONE"  # the account was deleted: terminal, never retried


class AccountGone(Exception):
    """The account a request was authenticated for was deleted while it ran: nothing was written for it, and the
    request ends as unauthenticated (the session is gone with the account)."""


@runtime_checkable
class StatementImportWrites(Protocol):
    """One statement import's writes in one transaction (ADR-048 §8): the new statements, the transactions they post,
    and the audit events, its memory evidence transitions included. The import prepares everything outside it.

    In accounts mode an import may write only for an existing account or an enabled shared demo persona; the check
    runs inside the commit's transaction, before the token, so an import that started before an account deletion
    recreates nothing for it. Demo mode (no accounts) keeps its owners as they are."""

    def token(self, user_id: str) -> str:
        """An opaque fingerprint of everything an import decides on for this user: their statements, the content of
        their transactions (a category changed under the same txn_id included), their declarations and their memory
        consent and counters. Any committed write to one of them changes it."""
        ...

    def commit(
        self, user_id: str, token: str, statements: Sequence[StoredStatement], transactions: Sequence[PostedTransaction],
        events: Sequence[AuditDraft],
    ) -> ImportCommit:
        """OWNER_GONE, with no writes, if the owner may no longer be written (see above); CHANGED, with no writes, if
        token(user_id) is no longer `token`: prepare again. Otherwise COMMITTED: the statements and transactions, all
        new to this user, stored and the events appended, together. Raises ValueError for rows or events of another
        owner and IdCollision for a statement, transaction or event that already exists; any exception leaves no
        writes."""
        ...


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
class KnowledgeBase(Protocol):
    """Finds the concept cards that explain a question (ADR-040). Retrieval only: it never writes an answer.

    Swap the method by registering another adapter in bootstrap (KNOWLEDGE_BASES); nothing else changes.
    """

    name: str  # method + embedder + corpus hash; recorded on every explanation, changes when any of them change

    def search(self, query: str, lang: str, k: int) -> Sequence[Passage]:
        """Up to k passages, best first, preferring cards in `lang`; scores in [0, 1]."""
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

    def has_transactions(self, user_id: str) -> bool:
        """Whether this user has any posted transaction; cheap, without reading their payloads."""
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
class InvestmentProvider(Protocol):
    """Reads an account at an investment institution (ADR-044). Read-only: it signs in and lists goals, nothing else.

    The password reaches only `authenticate` and travels to the provider over HTTPS; the token it returns is what the
    store keeps, sealed. An adapter never puts a credential in an error, a log or a return value other than the token.
    """

    name: str  # the adapter: "fintual" (the provider's API) | "fixture" (offline, synthetic)
    provider: str  # the institution: a key of domain/investments/model.py PROVIDERS
    synthetic: bool  # True when the goals it returns are invented sandbox data

    def authenticate(self, email: str, password: str) -> str:
        """An access token. InvestmentAccessRejected for credentials the provider refuses; InvestmentProviderUnavailable otherwise."""
        ...

    def goals(self, email: str, token: str) -> tuple[ReportedGoal, ...]:
        """Every goal of the account, as reported now. InvestmentAccessRejected when the token is no longer accepted."""
        ...


@runtime_checkable
class InvestmentStore(Protocol):
    """A user's investment link and the snapshots synced through it, sealed at rest (G11). Each write commits with its
    audit events or not at all, and is a compare-and-set against the link the caller read."""

    def link(self, user_id: str) -> InvestmentLink | None: ...

    def latest(self, user_id: str) -> InvestmentSnapshot | None:
        """The most recent snapshot of the user, or None."""
        ...

    def save(
        self, expected: InvestmentLink | None, link: InvestmentLink, snapshot: InvestmentSnapshot | None, events: Sequence[AuditDraft]
    ) -> bool:
        """Replace the user's link with `link` and append `snapshot` (when given), keeping the newest MAX_SNAPSHOTS.

        False, with no writes, if the stored link no longer equals `expected` (None: no link). Raises ValueError when
        the link, the snapshot or an event belongs to another user, and IdCollision on a reused event id."""
        ...

    def remove(self, user_id: str, events: Sequence[AuditDraft]) -> int:
        """Delete the link and every snapshot of the user with the events. Returns the rows deleted; 0 (and no
        events written) when nothing was linked. Imported documents stay: they are removed on their own."""
        ...

    def add_document(self, document: StoredInvestmentDocument, events: Sequence[AuditDraft]) -> bool:
        """Store a verified document with its events, keeping the user's MAX_DOCUMENTS newest imports.
        False, with no writes, when the user already has a document with that id. Raises ValueError when the document
        or an event belongs to another user, and IdCollision on a reused event id."""
        ...

    def documents(self, user_id: str) -> tuple[StoredInvestmentDocument, ...]:
        """The user's documents, oldest import first."""
        ...

    def remove_documents(self, user_id: str, events: Sequence[AuditDraft]) -> int:
        """Delete every document of the user with the events. Returns how many; 0 (and no events written) when none."""
        ...


@runtime_checkable
class InvestmentDocumentReader(Protocol):
    """Reads a statement an investment provider issues (ADR-044): the rows only, never the holder's name or RUT.

    Never decides whether the rows add up: that is domain/investments/documents `check_document`. Raises
    StatementUnreadable for a file that is not a document it knows and StatementReaderUnavailable when an extra it
    needs (pdfplumber, OCR) is missing.
    """

    name: str  # reported with every document it reads

    def read(self, content: bytes) -> ReadInvestmentDocument: ...


@runtime_checkable
class SnapshotStore(Protocol):
    """Computed results by snapshot id. Proposals take their amount from here, never from model text."""

    def put(self, snapshot_id: str, user_id: str, value: object) -> None: ...

    def get(self, snapshot_id: str, user_id: str) -> object | None: ...

    def forget(self, user_id: str) -> int:
        """Drop every snapshot of this user (account deletion). Returns how many."""
        ...


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
class MemoryStore(Protocol):
    """The declarations a user confirmed (ADR-048): one chain per user and type, its versions appended, never edited.

    Every read and write names the owner: another user's chain is not found, and their rows are never touched.
    Conclusions (verified, conflict) are never stored here; domain/memory derives them on read.
    """

    def for_user(self, user_id: str) -> tuple[Declaration, ...]:
        """Every declaration of the user, superseded versions included, in chain then version order (the export)."""
        ...

    def chain(self, user_id: str, chain_id: str) -> tuple[Declaration, ...]:
        """This user's chain in version order; empty if it does not exist or is another user's."""
        ...

    def chain_of_type(self, user_id: str, type: MemoryType) -> tuple[Declaration, ...]:
        """The user's only chain of this type in version order, or empty."""
        ...

    def append(self, declarations: Sequence[Declaration], expected_version: int) -> bool:
        """Append consecutive versions of one chain (a base and a change confirmed together), all or none.

        Compare-and-set on the head: expected_version is the chain's last version, 0 for a new chain. False, with no
        writes, if the head moved, or if a new chain is started while the user already has one of that type.
        Raises ValueError for a batch that mixes chains, owners or types, whose versions do not follow
        expected_version, or that holds a declaration outside contracts/memory/declaration.schema.json (one the
        stored record would not read back identically), and IdCollision for a memory_id or chain_id already used elsewhere; any exception also
        leaves no writes.
        """
        ...

    def delete_chain(self, user_id: str, chain_id: str) -> int:
        """Delete every version of this user's chain at once. Returns how many; 0 for another user's chain."""
        ...


@dataclass(frozen=True, slots=True)
class MemoryWriteResult:
    outcome: WriteOutcome
    state: MemoryState | None = None  # the user's consent and counters after the write (or as found, when refused)
    changed: bool = False  # set_consent: whether the consent actually changed
    deleted_versions: int = 0  # delete_chain
    invalidated_proposals: int = 0  # delete_chain and a revoking set_consent


@runtime_checkable
class MemoryWrites(Protocol):
    """Every memory write that has to be atomic (ADR-048 §5-6), next to the reads it decides on.

    Each write runs as one transaction over every store it touches: it checks there that the account still exists
    (a request authenticated before the account was deleted recreates nothing; a shared persona has no account and
    is never writable), reads the state it decides on, applies the domain's decision (domain/memory/proposals.py)
    and commits its rows and audit events together. A refusal is an outcome with no writes; any exception also
    leaves no writes. Audit details are codes, references and counts, never an amount or a message.
    """

    def state(self, user_id: str) -> MemoryState:
        """The user's consent and counters; missing, 0 and 0 for a user with none."""
        ...

    def proposal(self, user_id: str, proposal_id: str) -> MemoryProposal | None:
        """The user's own proposal; None if unknown or another user's."""
        ...

    def set_consent(self, user_id: str, requested: Consent, event: AuditDraft) -> MemoryWriteResult:
        """Grant or revoke. An actual change advances the consent generation and appends `event` with its detail
        replaced by the transition's codes; a repeated update changes nothing and appends nothing. Revoking also
        invalidates every pending proposal of the user; declarations stay."""
        ...

    def prepare(self, proposal: MemoryProposal) -> MemoryWriteResult:
        """Store a pending proposal, never a declaration, if the account exists, consent is granted and the consent
        generation and memory revision it captured are still current."""
        ...

    def confirm(
        self, user_id: str, proposal_id: str | None, declarations: Sequence[Declaration], expected_version: int,
        now: datetime, event: AuditDraft,
    ) -> MemoryWriteResult:
        """Decide with decide_confirmation; on DONE consume the proposal (when one is named), append the
        declarations (one version, or a base and a change) as MemoryStore.append would, advance the memory revision
        and append `event` (MEMORY_CONFIRMED) with its detail replaced by the confirmation's codes and counts. Raises
        ValueError for a batch MemoryStore.append refuses, another owner, or a declaration whose audit_ref is not
        `event`'s id."""
        ...

    def delete_chain(self, user_id: str, chain_id: str, event: AuditDraft) -> MemoryWriteResult:
        """Delete every version of the user's chain, invalidate the user's pending proposals (none can restore it),
        advance the memory revision and append `event` with its detail replaced by the
        counts. NOT_FOUND for an unknown or another user's chain. Needs no consent."""
        ...


@runtime_checkable
class ConversationStore(Protocol):
    def history(self, user_id: str, session_id: str) -> tuple[Entry, ...]: ...

    def append(self, user_id: str, session_id: str, entries: Sequence[Entry], keep_last: int) -> None: ...

    def forget(self, user_id: str) -> int:
        """Drop every conversation of this user (account deletion). Returns how many sessions."""
        ...


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
class EmailDomainCheck(Protocol):
    """Whether sign-up accepts the domain of a normalized email: why not, or None to accept. Sign-in never asks."""

    def refusal(self, email: str) -> str | None: ...


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


@dataclass(frozen=True, slots=True)
class ErasureReport:
    counts: Mapping[str, int]  # rows deleted per table
    erased_events: int  # audit events turned into tombstones


@runtime_checkable
class AccountErasure(Protocol):
    """Delete everything a user owns, in one atomic step (Ley 21.719 art. 7, G03)."""

    def erase(self, user_id: str, *, keep_account: bool, event: AuditDraft) -> ErasureReport:
        """Delete the user's statements, transactions, memory, savings rules, proposals and authorizations and, unless
        keep_account (a demo persona's reset), their sessions, profile and account. Every audit event of the user
        becomes a tombstone (domain/audit/events.py), then `event` is appended with its detail replaced by
        erasure_detail(), which commits to exactly those tombstones. Any exception leaves no writes."""
        ...


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


@runtime_checkable
class McpClient(Protocol):
    """Talks to an MCP server the user added (ADR-047). Only the user's sync uses it; no agent tool reaches it.

    Checks the address before every request (domain/connections/model.py:check_target) and raises TargetRefused,
    and raises ConnectorUnavailable on any network, protocol or size error. The token goes to that server only.
    """

    def list_tools(self, url: str, token: str | None) -> Sequence[Any]:
        """The `tools` array of tools/list, as the server sent it (untrusted)."""
        ...

    def call_tool(self, url: str, token: str | None, name: str) -> Any:
        """tools/call with empty arguments; the structured content, or the text content parsed as JSON if it is."""
        ...


@runtime_checkable
class BankFeed(Protocol):
    """A bank aggregator (Fintoc, ADR-047): read-only accounts and movements behind a link the user created."""

    name: str  # the aggregator, shown as the connection's host and used as the statements' bank code
    public_key: str | None  # for the widget; None when no widget is needed (fixture)

    def start(self) -> str | None:
        """A one-time widget token for a new link (Fintoc's link intent); None when no widget is needed (fixture).
        Raises ConnectorUnavailable."""
        ...

    def exchange(self, exchange_token: str) -> str:
        """Trade the widget's exchange token for the link token. Raises ConnectorUnavailable."""
        ...

    def fetch(self, link_token: str, since: date | None) -> Sequence[tuple[BankAccount, Sequence[BankMovement]]]:
        """Each account with its movements posted on or after `since` (all available if None). Raises ConnectorUnavailable."""
        ...


@runtime_checkable
class ConnectionStore(Protocol):
    """A user's connections, each with its sealed secret and the latest answer per tool."""

    def add(self, connection: Connection, secret: str | None) -> None: ...

    def get(self, user_id: str, connection_id: str) -> Connection | None: ...

    def for_user(self, user_id: str) -> tuple[Connection, ...]:
        """Oldest first."""
        ...

    def update(self, connection: Connection) -> bool:
        """Replace this user's connection with the same id, keeping its secret. False if it is not stored."""
        ...

    def secret(self, user_id: str, connection_id: str) -> str | None: ...

    def put_results(self, user_id: str, connection_id: str, results: Sequence[ConnectionSnapshot]) -> None:
        """Replace every stored answer of this connection with these."""
        ...

    def results(self, user_id: str, connection_id: str) -> tuple[ConnectionSnapshot, ...]: ...

    def remove(self, user_id: str, connection_id: str) -> bool:
        """Delete the connection, its secret and its answers. False if it was not stored."""
        ...
