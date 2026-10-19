"""Sign-up, sign-in and sessions. HTTP-only flows: the agent has no tool for any of them.

They commit account state with its audit events through AccountWrites. They return AccountOutcome,
never an Envelope, because a session token must never travel in an
envelope. The token exists only in IssuedSession, for the HTTP adapter to set as a cookie; the
store keeps its digest. Audit records carry the session_ref, never the email, the display name,
the password or the token. Every sign-in failure is the same outcome and costs one password check,
so neither the answer nor its timing says whether an email has an account.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum

from ...domain.audit.events import Actor, AuditDraft, AuditKind
from ...domain.shared.errors import InvalidInput
from ...domain.user.account import SESSION_PREFIX, USER_PREFIX, Session, UserAccount, normalize_email, token_digest, validate_password
from ...domain.user.profile import UserProfile
from ..ports import AccountWrites, Clock, IdGenerator, PasswordHasher, SessionStore, TokenGenerator, TransactionStore, UserAccountStore


class AccountStatus(str, Enum):
    OK = "OK"
    INVALID_INPUT = "INVALID_INPUT"
    EMAIL_TAKEN = "EMAIL_TAKEN"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    NOT_FOUND = "NOT_FOUND"


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

    @property
    def ok(self) -> bool:
        return self.status is AccountStatus.OK


INVALID_CREDENTIALS = AccountOutcome(AccountStatus.INVALID_CREDENTIALS, message="invalid credentials")
EMAIL_TAKEN = AccountOutcome(AccountStatus.EMAIL_TAKEN, field="email", message="email already registered")
UNKNOWN_PERSONA = AccountOutcome(AccountStatus.INVALID_INPUT, field="persona", message="choose an available demo persona")

# The only public, read-only personas a demo session can open. Never an arbitrary user id.
DEMO_PERSONAS: tuple[str, ...] = ("camila", "diego")


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
    ) -> None:
        if not demo_personas <= frozenset(DEMO_PERSONAS):
            raise ValueError("demo sessions open only the allowlisted personas")
        self._demo_personas = frozenset(demo_personas)
        self._transactions = transactions  # only to tell an account with imported statements from an empty one
        self._accounts = accounts
        self._sessions = sessions
        self._writes = writes
        self._hasher = hasher
        self._tokens = tokens
        self._clock = clock
        self._ids = ids

    def signup(self, email: str, password: str, display_name: str, language: str = "en") -> AccountOutcome:
        """Creates the account, an empty profile (no tolerance, no questionnaire) and signs the user in."""
        try:
            normalized = normalize_email(email)
            validate_password(password)
            draft = UserProfile("", display_name, language)
        except InvalidInput as error:
            return AccountOutcome(AccountStatus.INVALID_INPUT, field=error.field, message=error.message)
        if self._accounts.by_email(normalized) is not None:
            return EMAIL_TAKEN
        password_hash = self._hasher.hash(password)
        user_id = self._ids.new(USER_PREFIX)
        now = self._clock.now()
        token, session = self._new_session(user_id, now)
        events = (
            self._draft(AuditKind.USER_REGISTERED, user_id, session.session_ref, None, now),
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

    def _new_session(self, user_id: str, now: datetime) -> tuple[str, Session]:
        token = self._tokens.new_token()
        session = Session.open(self._ids.new(SESSION_PREFIX), user_id, token_digest(token), now)
        return token, session

    def _draft(self, kind: AuditKind, user_id: str, session_ref: str, detail: str | None, now: datetime) -> AuditDraft:
        return AuditDraft(
            event_id=self._ids.new("evt"), timestamp=now, session_id=session_ref,
            user_id=user_id, actor=Actor.USER, kind=kind, detail=detail,
        )
