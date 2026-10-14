"""Sign-up, sign-in and sessions. HTTP-only flows: the agent has no tool for any of them.

They return AccountOutcome, never an Envelope, because a session token must never travel in an
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
from ..ports import AuditLog, Clock, IdGenerator, PasswordHasher, SessionStore, TokenGenerator, UserAccountStore, UserProfileStore


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


class AccountUseCases:
    def __init__(
        self,
        accounts: UserAccountStore,
        sessions: SessionStore,
        profiles: UserProfileStore,
        hasher: PasswordHasher,
        tokens: TokenGenerator,
        audit: AuditLog,
        clock: Clock,
        ids: IdGenerator,
    ) -> None:
        self._accounts = accounts
        self._sessions = sessions
        self._profiles = profiles
        self._hasher = hasher
        self._tokens = tokens
        self._audit = audit
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
        # Profile first: a lost race leaves an unreachable profile, never an account without one.
        self._profiles.put(replace(draft, user_id=user_id))
        if not self._accounts.add(UserAccount(user_id, normalized, password_hash, now)):
            return EMAIL_TAKEN
        issued = self._issue(user_id, now)
        self._record(AuditKind.USER_REGISTERED, user_id, issued.session_ref, None)
        self._record(AuditKind.SESSION_STARTED, user_id, issued.session_ref, "reason=signup")
        return AccountOutcome(AccountStatus.OK, session=issued)

    def signin(self, email: str, password: str) -> AccountOutcome:
        try:
            account = self._accounts.by_email(normalize_email(email))
        except InvalidInput:
            account = None
        matches = self._hasher.verify(password, account.password_hash if account is not None else None)
        if account is None or not matches:
            return INVALID_CREDENTIALS
        issued = self._issue(account.user_id, self._clock.now())
        self._record(AuditKind.SESSION_STARTED, account.user_id, issued.session_ref, "reason=signin")
        return AccountOutcome(AccountStatus.OK, session=issued)

    def resolve(self, token: str) -> Session | None:
        """The active session for this token. Read-only: using a session never extends it."""
        if not isinstance(token, str) or not token:
            return None
        session = self._sessions.by_token_hash(token_digest(token))
        return session if session is not None and session.is_active(self._clock.now()) else None

    def signout(self, token: str) -> bool:
        session = self.resolve(token)
        if session is None or not self._sessions.revoke(session.session_ref, self._clock.now()):
            return False
        self._record(AuditKind.SESSION_ENDED, session.user_id, session.session_ref, "reason=signout")
        return True

    def set_sample_data(self, user_id: str, session_ref: str, enabled: bool) -> AccountOutcome:
        """Stores the user's choice only. Personas have no account, so they are NOT_FOUND here."""
        if not self._accounts.set_sample_data(user_id, enabled):
            return AccountOutcome(AccountStatus.NOT_FOUND, field="user_id", message="no account for this user")
        self._record(AuditKind.PROFILE_UPDATED, user_id, session_ref, f"fields=sample_data;enabled={'true' if enabled else 'false'}")
        return AccountOutcome(AccountStatus.OK)

    def _issue(self, user_id: str, now: datetime) -> IssuedSession:
        token = self._tokens.new_token()
        session = Session.open(self._ids.new(SESSION_PREFIX), user_id, token_digest(token), now)
        self._sessions.add(session)
        return IssuedSession(user_id, session.session_ref, session.expires_at, token)

    def _record(self, kind: AuditKind, user_id: str, session_ref: str, detail: str | None) -> None:
        self._audit.append(AuditDraft(
            event_id=self._ids.new("evt"), timestamp=self._clock.now(), session_id=session_ref,
            user_id=user_id, actor=Actor.USER, kind=kind, detail=detail,
        ))
