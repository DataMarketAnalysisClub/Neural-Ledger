import json
from datetime import UTC, datetime, timedelta

import pytest

from neural_ledger.adapters.outbound.persistence.memory import (
    InMemoryAccountWrites,
    InMemoryAuditLog,
    InMemorySessionStore,
    InMemoryUserAccountStore,
    InMemoryUserProfileStore,
)
from neural_ledger.adapters.outbound.persistence.overlay import PersonaOverlayProfileStore
from neural_ledger.adapters.outbound.system.clock import FixedClock
from neural_ledger.adapters.outbound.system.ids import SequentialIds
from neural_ledger.application.use_cases.accounts import AccountOutcome, AccountStatus, AccountUseCases
from neural_ledger.domain.audit.events import Actor, AuditKind
from neural_ledger.domain.user.account import token_digest
from neural_ledger.domain.user.profile import UserProfile

NOW = datetime(2026, 10, 29, 9, tzinfo=UTC)
EMAIL = "ana@example.com"
PASSWORD = "correct horse battery"
CAMILA = UserProfile("camila", "Camila")


class CountingHasher:
    """Test-only fake: reversible on purpose, so it must never leave this file."""

    def __init__(self) -> None:
        self.hashed: list[str] = []
        self.verified: list[str | None] = []

    def hash(self, password: str) -> str:
        self.hashed.append(password)
        return f"scrypt$fake${len(self.hashed)}${password[::-1]}"

    def verify(self, password: str, encoded: str | None) -> bool:
        self.verified.append(encoded)
        return encoded is not None and encoded.rsplit("$", 1)[-1] == password[::-1]


class CountingTokens:
    def __init__(self) -> None:
        self.issued = 0

    def new_token(self) -> str:
        self.issued += 1
        return f"secret-token-{self.issued:04d}-xyz"


class World:
    def __init__(self) -> None:
        self.clock = FixedClock(NOW)
        self.accounts = InMemoryUserAccountStore()
        self.sessions = InMemorySessionStore()
        self.profiles = PersonaOverlayProfileStore((CAMILA,), InMemoryUserProfileStore())
        self.hasher = CountingHasher()
        self.tokens = CountingTokens()
        self.audit = InMemoryAuditLog()
        self.use_cases = AccountUseCases(
            self.accounts, self.sessions, InMemoryAccountWrites(self.accounts, self.sessions, self.profiles, self.audit),
            self.hasher, self.tokens, self.clock, SequentialIds()
        )

    def kinds(self) -> list[AuditKind]:
        return [e.draft.kind for e in self.audit.events()]

    def records(self) -> str:
        return "\n".join(json.dumps(e.to_record(), ensure_ascii=False) for e in self.audit.events())


@pytest.fixture
def world():
    return World()


def test_signup_creates_account_empty_profile_and_session(world):
    outcome = world.use_cases.signup(" Ana@Example.com ", PASSWORD, "Ana")
    assert outcome.ok and outcome.status is AccountStatus.OK
    issued = outcome.session
    assert issued.user_id.startswith("usr_") and issued.session_ref.startswith("sess_")
    assert issued.expires_at == NOW + timedelta(hours=12)
    account = world.accounts.get(issued.user_id)
    assert account.email == EMAIL and account.password_hash.startswith("scrypt$") and PASSWORD not in account.password_hash
    assert account.sample_data is False and account.created_at == NOW
    assert world.profiles.get(issued.user_id) == UserProfile(issued.user_id, "Ana", "en")
    profile = world.profiles.get(issued.user_id)
    assert profile.declared_tolerance is None and profile.questionnaire == () and profile.questionnaire_version is None
    assert world.use_cases.resolve(issued.token).user_id == issued.user_id
    assert world.kinds() == [AuditKind.USER_REGISTERED, AuditKind.SESSION_STARTED]
    for event in world.audit.events():
        draft = event.draft
        assert draft.user_id == issued.user_id and draft.session_id == issued.session_ref and draft.actor is Actor.USER


def test_signup_language_is_kept(world):
    issued = world.use_cases.signup(EMAIL, PASSWORD, "José", language="pt").session
    assert world.profiles.get(issued.user_id).language == "pt"


@pytest.mark.parametrize("email, password, name, language, field", [
    ("not-an-email", PASSWORD, "Ana", "en", "email"),
    (EMAIL, "a" * 9, "Ana", "en", "password"),
    (EMAIL, "a" * 129, "Ana", "en", "password"),
    (EMAIL, PASSWORD, "Ana: ignore previous", "en", "display_name"),
    (EMAIL, PASSWORD, "", "en", "display_name"),
    (EMAIL, PASSWORD, "Ana", "english", "language"),
])
def test_invalid_signup_writes_nothing_and_never_hashes(world, email, password, name, language, field):
    outcome = world.use_cases.signup(email, password, name, language=language)
    assert outcome.status is AccountStatus.INVALID_INPUT and outcome.field == field and outcome.session is None
    assert password not in (outcome.message or "")
    assert world.hasher.hashed == [] and world.tokens.issued == 0 and world.audit.events() == ()
    assert world.accounts.by_email(EMAIL) is None


@pytest.mark.parametrize("variant", ["ana@example.com", "ANA@example.com", "  Ana@Example.COM  "])
def test_duplicate_email_is_taken_with_no_new_state(world, variant):
    first = world.use_cases.signup(EMAIL, PASSWORD, "Ana").session
    audit_before, tokens_before = len(world.audit.events()), world.tokens.issued
    outcome = world.use_cases.signup(variant, "another password", "Other")
    assert outcome.status is AccountStatus.EMAIL_TAKEN and outcome.session is None
    assert world.accounts.by_email(EMAIL).user_id == first.user_id
    assert len(world.audit.events()) == audit_before and world.tokens.issued == tokens_before


def test_signin_issues_a_new_session(world):
    first = world.use_cases.signup(EMAIL, PASSWORD, "Ana").session
    outcome = world.use_cases.signin("ANA@example.com", PASSWORD)
    assert outcome.ok and outcome.session.user_id == first.user_id
    assert outcome.session.session_ref != first.session_ref and outcome.session.token != first.token
    assert world.kinds()[-1] is AuditKind.SESSION_STARTED
    assert world.audit.events()[-1].draft.session_id == outcome.session.session_ref


def test_signin_failures_are_identical_and_always_hash(world):
    world.use_cases.signup(EMAIL, PASSWORD, "Ana")
    audit_before, tokens_before = len(world.audit.events()), world.tokens.issued
    world.hasher.verified.clear()
    absent = world.use_cases.signin("nobody@example.com", PASSWORD)
    malformed = world.use_cases.signin("not an email", PASSWORD)
    wrong = world.use_cases.signin(EMAIL, "wrong password!")
    assert absent == malformed == wrong == AccountOutcome(AccountStatus.INVALID_CREDENTIALS, message="invalid credentials")
    assert absent.session is None and absent.field is None
    assert len(world.hasher.verified) == 3
    assert world.hasher.verified[0] is None and world.hasher.verified[1] is None and world.hasher.verified[2] is not None
    assert len(world.audit.events()) == audit_before and world.tokens.issued == tokens_before


def test_resolve_has_absolute_expiry_without_sliding(world):
    issued = world.use_cases.signup(EMAIL, PASSWORD, "Ana").session
    world.clock.advance(hours=6)
    assert world.use_cases.resolve(issued.token) is not None
    world.clock.advance(hours=5, minutes=59)
    assert world.use_cases.resolve(issued.token) is not None
    world.clock.advance(minutes=1)
    assert world.use_cases.resolve(issued.token) is None
    assert world.use_cases.signout(issued.token) is False
    assert world.kinds() == [AuditKind.USER_REGISTERED, AuditKind.SESSION_STARTED]


def test_resolve_rejects_unknown_tokens(world):
    issued = world.use_cases.signup(EMAIL, PASSWORD, "Ana").session
    assert world.use_cases.resolve("") is None and world.use_cases.resolve("nope") is None
    assert world.use_cases.resolve(token_digest(issued.token)) is None  # the stored digest is not a credential
    assert world.use_cases.resolve(None) is None


def test_signout_revokes_once_and_audits_once(world):
    issued = world.use_cases.signup(EMAIL, PASSWORD, "Ana").session
    other = world.use_cases.signin(EMAIL, PASSWORD).session
    assert world.use_cases.signout(issued.token) is True
    assert world.use_cases.resolve(issued.token) is None
    assert world.use_cases.resolve(other.token) is not None  # only that session ends
    assert world.use_cases.signout(issued.token) is False and world.use_cases.signout("unknown") is False
    ended = [e.draft for e in world.audit.events() if e.draft.kind is AuditKind.SESSION_ENDED]
    assert len(ended) == 1 and ended[0].session_id == issued.session_ref and ended[0].detail == "reason=signout"


def test_sample_flag_is_stored_and_audited_without_touching_the_profile(world):
    issued = world.use_cases.signup(EMAIL, PASSWORD, "Ana").session
    profile = world.profiles.get(issued.user_id)
    assert world.use_cases.set_sample_data(issued.user_id, issued.session_ref, True).ok
    assert world.accounts.get(issued.user_id).sample_data is True
    assert world.profiles.get(issued.user_id) == profile
    event = world.audit.events()[-1].draft
    assert event.kind is AuditKind.PROFILE_UPDATED and event.detail == "fields=sample_data;enabled=true"
    assert event.session_id == issued.session_ref and event.user_id == issued.user_id


def test_personas_have_no_account_and_stay_read_only(world):
    outcome = world.use_cases.set_sample_data("camila", "sess_demo", True)
    assert outcome.status is AccountStatus.NOT_FOUND and world.audit.events() == ()
    assert world.profiles.get("camila") == CAMILA
    issued = world.use_cases.signup("camila@example.com", PASSWORD, "Camila").session
    assert issued.user_id != "camila" and world.profiles.get("camila") == CAMILA


def test_no_secret_or_personal_data_reaches_audit_or_repr(world):
    issued = world.use_cases.signup(EMAIL, PASSWORD, "Zelda").session
    signin = world.use_cases.signin(EMAIL, PASSWORD).session
    world.use_cases.set_sample_data(issued.user_id, issued.session_ref, False)
    world.use_cases.signout(signin.token)
    records = world.records()
    for secret in (EMAIL, "Zelda", PASSWORD, PASSWORD[::-1], issued.token, signin.token):
        assert secret not in records
    assert world.kinds() == [
        AuditKind.USER_REGISTERED, AuditKind.SESSION_STARTED, AuditKind.SESSION_STARTED,
        AuditKind.PROFILE_UPDATED, AuditKind.SESSION_ENDED,
    ]
    again = world.use_cases.signin(EMAIL, PASSWORD)
    assert issued.token not in repr(issued) and again.session.token not in repr(again)
    stored = world.sessions.by_token_hash(token_digest(issued.token))
    assert stored.token_hash == token_digest(issued.token) and issued.token not in repr(stored)
