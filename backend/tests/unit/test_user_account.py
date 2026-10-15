from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from neural_ledger.domain.shared.errors import InvalidInput
from neural_ledger.domain.shared.hashing import sha256_hex
from neural_ledger.domain.user.account import (
    SESSION_TTL,
    Session,
    UserAccount,
    normalize_email,
    token_digest,
    validate_password,
)

NOW = datetime(2026, 10, 29, 9, tzinfo=UTC)
HASH = "scrypt$16384$8$1$c2FsdHNhbHRzYWx0c2FsdA==$aGFzaGhhc2hoYXNoaGFzaA=="


@pytest.mark.parametrize("raw, expected", [
    ("Ana@Example.COM", "ana@example.com"),
    ("  ana@example.com\t", "ana@example.com"),
    ("ana.maria+cash@mail.example.cl", "ana.maria+cash@mail.example.cl"),
])
def test_email_is_trimmed_and_lowercased(raw, expected):
    assert normalize_email(raw) == expected


@pytest.mark.parametrize("raw", [
    "", "ana", "ana@", "@example.com", "ana@example", "ana@@example.com", "ana@b@example.com",
    "ana maria@example.com", "ana@exa\u0000mple.com", "ana@example..com", "ana@.example.com",
    "a" * 250 + "@example.com", None,
])
def test_invalid_email_is_rejected_without_echoing_it(raw):
    with pytest.raises(InvalidInput) as error:
        normalize_email(raw)
    assert error.value.field == "email"
    if raw:
        assert raw.strip() not in error.value.message


@pytest.mark.parametrize("password", ["a" * 10, "a" * 128, "correct horse", "ñ" * 10])
def test_password_policy_accepts_10_to_128_characters(password):
    assert validate_password(password) == password


@pytest.mark.parametrize("password", ["", "a" * 9, "a" * 129, None])
def test_password_policy_rejects_other_lengths_without_echoing(password):
    with pytest.raises(InvalidInput) as error:
        validate_password(password)
    assert error.value.field == "password"
    if password:
        assert password not in error.value.message


def test_token_digest_is_sha256_of_the_token():
    assert token_digest("tok") == sha256_hex("tok") and len(token_digest("tok")) == 64


def test_account_hides_email_and_hash_from_repr():
    account = UserAccount("usr_000001", "ana@example.com", HASH, NOW)
    assert account.sample_data is False
    assert "ana@example.com" not in repr(account) and HASH not in repr(account)


@pytest.mark.parametrize("changes", [
    {"user_id": "camila"},
    {"email": "Ana@Example.com"},
    {"password_hash": "plaintext-password"},
    {"created_at": datetime(2026, 10, 29, 9)},
])
def test_account_invariants(changes):
    base = dict(user_id="usr_000001", email="ana@example.com", password_hash=HASH, created_at=NOW)
    with pytest.raises(InvalidInput):
        UserAccount(**{**base, **changes})


def test_session_has_absolute_twelve_hour_expiry():
    session = Session.open("sess_000001", "usr_000001", token_digest("tok"), NOW)
    assert SESSION_TTL == timedelta(hours=12) and session.expires_at == NOW + SESSION_TTL
    assert session.is_active(NOW) and session.is_active(NOW + timedelta(hours=11, minutes=59))
    assert not session.is_active(NOW + SESSION_TTL)
    assert not replace(session, revoked_at=NOW).is_active(NOW)


def test_session_never_holds_the_token():
    session = Session.open("sess_000001", "camila", token_digest("tok"), NOW)
    assert "tok" not in [getattr(session, name) for name in session.__slots__]
    assert session.user_id == "camila"  # persona demo sessions stay possible


@pytest.mark.parametrize("changes", [
    {"session_ref": "evt_000001"},
    {"token_hash": "tok"},
    {"token_hash": "A" * 64},
    {"created_at": datetime(2026, 10, 29, 9)},
    {"expires_at": NOW + timedelta(hours=13)},
])
def test_session_invariants(changes):
    base = dict(session_ref="sess_000001", user_id="usr_000001", token_hash=token_digest("tok"), created_at=NOW, expires_at=NOW + SESSION_TTL)
    with pytest.raises(InvalidInput):
        Session(**{**base, **changes})
