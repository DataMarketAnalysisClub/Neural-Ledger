"""Accounts and sign-in sessions, kept apart from the agent-facing UserProfile.

The email, the password hash and the session token never reach the agent, an envelope, a log
or the audit. Only a digest of the token is stored, so a stolen database cannot sign anyone in.
Sessions expire 12 hours after they open, however much they are used (no sliding renewal).
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ..shared.errors import InvalidInput
from ..shared.hashing import sha256_hex

PASSWORD_MIN = 10
PASSWORD_MAX = 128
EMAIL_MAX = 254
SESSION_TTL = timedelta(hours=12)
USER_PREFIX = "usr"
SESSION_PREFIX = "sess"
HASH_SCHEME = "scrypt"

_HEX = frozenset("0123456789abcdef")


def normalize_email(raw: str) -> str:
    """Trimmed and lower-cased. The error never echoes the input."""
    email = raw.strip().lower() if isinstance(raw, str) else ""
    local, _, domain = email.partition("@")
    if (
        not local
        or not domain
        or "@" in domain
        or len(email) > EMAIL_MAX
        or "" in domain.split(".")
        or "." not in domain
        or any(ch.isspace() or unicodedata.category(ch).startswith("C") for ch in email)
    ):
        raise InvalidInput("email", "use a valid email address")
    return email


def validate_password(password: str) -> str:
    """Length only, counted in code points; no Unicode normalization. The error never echoes the input."""
    if not isinstance(password, str) or not PASSWORD_MIN <= len(password) <= PASSWORD_MAX:
        raise InvalidInput("password", f"use {PASSWORD_MIN}-{PASSWORD_MAX} characters")
    return password


def token_digest(token: str) -> str:
    return sha256_hex(token)


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


@dataclass(frozen=True, slots=True)
class UserAccount:
    user_id: str
    email: str = field(repr=False)
    password_hash: str = field(repr=False)
    created_at: datetime
    sample_data: bool = False  # the user chose to explore with sample data; read by the model source (PR4)

    def __post_init__(self) -> None:
        if not self.user_id.startswith(f"{USER_PREFIX}_"):
            raise InvalidInput("user_id", "accounts use generated user ids")
        if normalize_email(self.email) != self.email:
            raise InvalidInput("email", "store the normalized email")
        if not self.password_hash.startswith(f"{HASH_SCHEME}$"):
            raise InvalidInput("password_hash", "store only an encoded password hash")
        if not _aware(self.created_at):
            raise InvalidInput("created_at", "use a timezone-aware datetime")


@dataclass(frozen=True, slots=True)
class Session:
    session_ref: str  # not secret: the only session identifier that reaches the audit
    user_id: str
    token_hash: str = field(repr=False)
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.session_ref.startswith(f"{SESSION_PREFIX}_"):
            raise InvalidInput("session_ref", "sessions use generated session references")
        if not self.user_id:
            raise InvalidInput("user_id", "a session belongs to a user")
        if len(self.token_hash) != 64 or not set(self.token_hash) <= _HEX:
            raise InvalidInput("token_hash", "store only the sha256 digest of the token")
        if not all(_aware(t) for t in (self.created_at, self.expires_at) + ((self.revoked_at,) if self.revoked_at else ())):
            raise InvalidInput("created_at", "use timezone-aware datetimes")
        if self.expires_at != self.created_at + SESSION_TTL:
            raise InvalidInput("expires_at", "sessions expire a fixed time after they open")

    @classmethod
    def open(cls, session_ref: str, user_id: str, token_hash: str, now: datetime) -> Session:
        return cls(session_ref, user_id, token_hash, now, now + SESSION_TTL)

    def is_active(self, now: datetime) -> bool:
        return self.revoked_at is None and now < self.expires_at
