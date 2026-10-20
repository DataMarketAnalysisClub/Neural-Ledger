"""Sign-up, sign-in and sessions. HTTP-only flows: the agent has no tool for any of them.

They commit account state with its audit events through AccountWrites. They return AccountOutcome,
never an Envelope, because a session token must never travel in an
envelope. The token exists only in IssuedSession, for the HTTP adapter to set as a cookie; the
store keeps its digest. Audit records carry the session_ref, never the email, the display name,
the password or the token. Every sign-in failure is the same outcome and costs one password check,
so neither the answer nor its timing says whether an email has an account.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum
from typing import Protocol

from ...domain.audit.events import ERASED_SESSION, Actor, AuditDraft, AuditKind
from ...domain.shared.errors import InvalidInput
from ...domain.user.account import SESSION_PREFIX, USER_PREFIX, Session, UserAccount, normalize_email, token_digest, validate_password
from ...domain.user.profile import UserProfile
from ..ports import (
    AccountErasure,
    AccountWrites,
    Clock,
    EmailDomainCheck,
    ErasureReport,
    IdGenerator,
    PasswordHasher,
    SessionStore,
    TokenGenerator,
    TransactionStore,
    UserAccountStore,
)


class AccountStatus(str, Enum):
    OK = "OK"
    INVALID_INPUT = "INVALID_INPUT"
    EMAIL_TAKEN = "EMAIL_TAKEN"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    NOT_FOUND = "NOT_FOUND"
    DELETED = "DELETED"  # the account and everything it owned are gone
    RESET = "RESET"  # a demo persona's stored data is gone; the persona stays


@dataclass(frozen=True, slots=True)
class IssuedSession:
    user_id: str
    session_ref: str
    expires_at: datetime
    token: str = field(repr=False)  # for the session cookie only; never serialize it into a response body


@dataclass(frozen=True, slots=True)
class AccountOutcome:
    status: AccountStatus
    session: IssuedSession | None = None
    field: str | None = None
    message: str | None = None
    erased: ErasureReport | None = None  # DELETED and RESET only

    @property
    def ok(self) -> bool:
        return self.status in (AccountStatus.OK, AccountStatus.DELETED, AccountStatus.RESET)


INVALID_CREDENTIALS = AccountOutcome(AccountStatus.INVALID_CREDENTIALS, message="invalid credentials")
EMAIL_TAKEN = AccountOutcome(AccountStatus.EMAIL_TAKEN, field="email", message="email already registered")
UNKNOWN_PERSONA = AccountOutcome(AccountStatus.INVALID_INPUT, field="persona", message="choose an available demo persona")

# The only public, read-only personas a demo session can open. Never an arbitrary user id.
DEMO_PERSONAS: tuple[str, ...] = ("camila", "diego")

# The sandbox notice a new account acknowledges at sign-up (no real statements, no personal data). Bump it when
# the notice's wording changes, so USER_REGISTERED records which one the user accepted.
SANDBOX_NOTICE = "sandbox-1"

# What the user types to confirm, besides the password: DELETE (or the account's email) to delete an account,
# RESET to reset a shared demo persona, which has no password and is never deleted.
DELETE_CONFIRMATION = "DELETE"
RESET_CONFIRMATION = "RESET"


class Forgettable(Protocol):
    """A store that keeps per-user state outside the erasure transaction (conversations, snapshots: memory only)."""

    def forget(self, user_id: str) -> int: ...


class AccountUseCases:
    def __init__(
        self,
        accounts: UserAccountStore,
        sessions: SessionStore,
        writes: AccountWrites,
        hasher: PasswordHasher,
        tokens: TokenGenerator,
        clock: Clock,
        ids: IdGenerator,
        *,
        demo_personas: frozenset[str] = frozenset(),
        transactions: TransactionStore | None = None,
        erasure: AccountErasure | None = None,
        forget: Sequence[Forgettable] = (),
        email_checks: Sequence[EmailDomainCheck] = (),
    ) -> None:
        if not demo_personas <= frozenset(DEMO_PERSONAS):
            raise ValueError("demo sessions open only the allowlisted personas")
        self._demo_personas = frozenset(demo_personas)
        self._transactions = transactions  # only to tell an account with imported statements from an empty one
        self._erasure = erasure
        self._forget = tuple(forget)
        self._email_checks = tuple(email_checks)  # disposable providers, domains that take no mail (adapters/outbound/email)
        self._accounts = accounts
        self._sessions = sessions
        self._writes = writes
        self._hasher = hasher
        self._tokens = tokens
        self._clock = clock
        self._ids = ids

    def signup(
        self, email: str, password: str, display_name: str, language: str = "en", *, sandbox_notice: str | None = None
    ) -> AccountOutcome:
        """Creates the account, an empty profile (no tolerance, no questionnaire) and signs the user in.

        sandbox_notice is the version of the sandbox notice the user acknowledged; the HTTP route refuses a sign-up
        without the acknowledgement and passes SANDBOX_NOTICE, which USER_REGISTERED records."""
        try:
            normalized = normalize_email(email)
            validate_password(password)
            draft = UserProfile("", display_name, language)
        except InvalidInput as error:
            return AccountOutcome(AccountStatus.INVALID_INPUT, field=error.field, message=error.message)
        for check in self._email_checks:
            if (refusal := check.refusal(normalized)) is not None:
                return AccountOutcome(AccountStatus.INVALID_INPUT, field="email", message=refusal)
        if self._accounts.by_email(normalized) is not None:
            return EMAIL_TAKEN
        password_hash = self._hasher.hash(password)
        user_id = self._ids.new(USER_PREFIX)
        now = self._clock.now()
        token, session = self._new_session(user_id, now)
        events = (
            self._draft(
                AuditKind.USER_REGISTERED, user_id, session.session_ref, f"sandbox_notice={sandbox_notice}" if sandbox_notice else None, now
            ),
            self._draft(AuditKind.SESSION_STARTED, user_id, session.session_ref, "reason=signup", now),
        )
        if not self._writes.register(UserAccount(user_id, normalized, password_hash, now), replace(draft, user_id=user_id), session, events):
            return EMAIL_TAKEN
        return AccountOutcome(AccountStatus.OK, session=IssuedSession(user_id, session.session_ref, session.expires_at, token))

    def signin(self, email: str, password: str) -> AccountOutcome:
        try:
            account = self._accounts.by_email(normalize_email(email))
        except InvalidInput:
            account = None
        matches = self._hasher.verify(password, account.password_hash if account is not None else None)
        if account is None or not matches:
            return INVALID_CREDENTIALS
        now = self._clock.now()
        token, session = self._new_session(account.user_id, now)
        self._writes.open_session(session, (self._draft(AuditKind.SESSION_STARTED, account.user_id, session.session_ref, "reason=signin", now),))
        return AccountOutcome(AccountStatus.OK, session=IssuedSession(account.user_id, session.session_ref, session.expires_at, token))

    @property
    def demo_personas(self) -> tuple[str, ...]:
        return tuple(sorted(self._demo_personas))

    def start_demo_session(self, persona: str) -> AccountOutcome:
        """A session on a shared, read-only persona from the enabled allowlist. The value is never echoed."""
        if not isinstance(persona, str) or persona not in self._demo_personas:
            return UNKNOWN_PERSONA
        now = self._clock.now()
        token, session = self._new_session(persona, now)
        self._writes.open_session(session, (self._draft(AuditKind.SESSION_STARTED, persona, session.session_ref, "reason=demo_session", now),))
        return AccountOutcome(AccountStatus.OK, session=IssuedSession(persona, session.session_ref, session.expires_at, token))

    def data_source(self, user_id: str) -> str:
        """persona (no account: a demo session), sample (the account chose sample data), statements (the account
        has imported statements: its model comes from them, ADR-029) or empty."""
        account = self._accounts.get(user_id)
        if account is None:
            return "persona"
        if account.sample_data:
            return "sample"
        if self._transactions is not None and self._transactions.has_transactions(user_id):
            return "statements"
        return "empty"

    def resolve(self, token: str) -> Session | None:
        """The active session for this token. Read-only: using a session never extends it."""
        if not isinstance(token, str) or not token:
            return None
        session = self._sessions.by_token_hash(token_digest(token))
        return session if session is not None and session.is_active(self._clock.now()) else None

    def signout(self, token: str) -> bool:
        session = self.resolve(token)
        if session is None:
            return False
        now = self._clock.now()
        return self._writes.close_session(
            session, now, (self._draft(AuditKind.SESSION_ENDED, session.user_id, session.session_ref, "reason=signout", now),)
        )

    def set_sample_data(self, user_id: str, session_ref: str, enabled: bool) -> AccountOutcome:
        """Stores the user's choice only. Personas have no account, so they are NOT_FOUND here."""
        now = self._clock.now()
        event = self._draft(
            AuditKind.PROFILE_UPDATED, user_id, session_ref, f"fields=sample_data;enabled={'true' if enabled else 'false'}", now
        )
        if not self._writes.set_sample_data(user_id, enabled, (event,)):
            return AccountOutcome(AccountStatus.NOT_FOUND, field="user_id", message="no account for this user")
        return AccountOutcome(AccountStatus.OK)

    def delete_account(self, session: Session, password: str | None, confirm: str | None) -> AccountOutcome:
        """Delete the caller's account and everything it owns, or reset a demo persona (G03, Ley 21.719 art. 7).

        An account needs its password again and the confirmation DELETE (or its email); every session ends,
        since their rows go with it. A demo persona has no password and is shared by every visitor: it is never
        deleted, only reset (statements, transactions, rules, proposals and audit events erased; the fixture and
        the visitors' sessions stay) with the confirmation RESET. Either way the erasure is one audited event with
        no user id that commits to the audit events it erased."""
        if self._erasure is None:
            return AccountOutcome(AccountStatus.NOT_FOUND, field="user_id", message="account deletion is not available")
        user_id = session.user_id
        account = self._accounts.get(user_id)
        if account is None:
            if user_id not in self._demo_personas:
                return AccountOutcome(AccountStatus.NOT_FOUND, field="user_id", message="no account for this user")
            if confirm != RESET_CONFIRMATION:
                return AccountOutcome(AccountStatus.INVALID_INPUT, field="confirm", message=f"type {RESET_CONFIRMATION} to reset the demo data")
            return AccountOutcome(AccountStatus.RESET, erased=self._erase(user_id, AuditKind.DEMO_DATA_RESET, keep_account=True))
        if not _confirms(confirm, account.email):
            return AccountOutcome(AccountStatus.INVALID_INPUT, field="confirm", message=f"type {DELETE_CONFIRMATION} or your email to confirm")
        if not self._hasher.verify(password if isinstance(password, str) else "", account.password_hash):
            return INVALID_CREDENTIALS
        return AccountOutcome(AccountStatus.DELETED, erased=self._erase(user_id, AuditKind.ACCOUNT_DELETED, keep_account=False))

    def _erase(self, user_id: str, kind: AuditKind, *, keep_account: bool) -> ErasureReport:
        assert self._erasure is not None
        # No user id and no session on the event: after a deletion nothing may point at the user any more.
        event = AuditDraft(
            event_id=self._ids.new("evt"), timestamp=self._clock.now(), session_id=ERASED_SESSION,
            user_id=None, actor=Actor.USER, kind=kind,
        )
        report = self._erasure.erase(user_id, keep_account=keep_account, event=event)
        for store in self._forget:
            store.forget(user_id)
        return report

    def _new_session(self, user_id: str, now: datetime) -> tuple[str, Session]:
        token = self._tokens.new_token()
        session = Session.open(self._ids.new(SESSION_PREFIX), user_id, token_digest(token), now)
        return token, session

    def _draft(self, kind: AuditKind, user_id: str, session_ref: str, detail: str | None, now: datetime) -> AuditDraft:
        return AuditDraft(
            event_id=self._ids.new("evt"), timestamp=now, session_id=session_ref,
            user_id=user_id, actor=Actor.USER, kind=kind, detail=detail,
        )


def _confirms(confirm: str | None, email: str) -> bool:
    if not isinstance(confirm, str):
        return False
    if confirm.strip() == DELETE_CONFIRMATION:
        return True
    try:
        return normalize_email(confirm) == email
    except InvalidInput:
        return False
