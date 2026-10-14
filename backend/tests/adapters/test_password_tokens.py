import hashlib
import re
import string

import pytest

from neural_ledger.adapters.outbound.system.password import ScryptHasher
from neural_ledger.adapters.outbound.system.tokens import SecretsTokens
from neural_ledger.application.ports import PasswordHasher, TokenGenerator

ENCODED = re.compile(r"^scrypt\$\d+\$\d+\$\d+\$[A-Za-z0-9+/=]+\$[A-Za-z0-9+/=]+$")
PASSWORD = "correct horse battery"


@pytest.fixture(scope="module")
def hasher():
    return ScryptHasher()


@pytest.fixture(scope="module")
def stored(hasher):
    return hasher.hash(PASSWORD)


def test_adapters_satisfy_their_ports(hasher):
    assert isinstance(hasher, PasswordHasher) and isinstance(SecretsTokens(), TokenGenerator)


def test_hash_format_has_production_parameters_and_never_the_password(stored):
    assert ENCODED.match(stored)
    assert stored.split("$")[1:4] == ["16384", "8", "1"]
    assert PASSWORD not in stored


def test_same_password_hashes_differently(hasher, stored):
    assert hasher.hash(PASSWORD) != stored


def test_verify_accepts_only_the_right_password(hasher, stored):
    assert hasher.verify(PASSWORD, stored)
    assert not hasher.verify(PASSWORD + "x", stored)
    assert not hasher.verify(PASSWORD, None)


def _with_part(encoded: str, index: int, value: str) -> str:
    parts = encoded.split("$")
    parts[index] = value
    return "$".join(parts)


@pytest.mark.parametrize("mangle", [
    lambda s: "",
    lambda s: "plaintext",
    lambda s: s.replace("scrypt$", "bcrypt$", 1),
    lambda s: s + "$extra",
    lambda s: _with_part(s, 1, "16383"),       # n not a power of two
    lambda s: _with_part(s, 1, str(2**21)),    # n above the bound
    lambda s: _with_part(s, 1, "1024"),        # n below the production floor
    lambda s: _with_part(s, 2, "0"),           # r out of bounds
    lambda s: _with_part(s, 3, "99"),          # p out of bounds
    lambda s: _with_part(s, 1, "١٦٣٨٤"),       # non-ASCII digits
    lambda s: _with_part(s, 4, "not base64!"),
    lambda s: _with_part(s, 5, "!!!"),
    lambda s: _with_part(s, 5, "AAAA"),        # derived key too short
])
def test_malformed_or_out_of_bounds_hashes_fail_closed(hasher, stored, mangle):
    assert hasher.verify(PASSWORD, mangle(stored)) is False


def _spy(monkeypatch):
    calls = []
    real = hashlib.scrypt

    def spy(password, **kwargs):
        calls.append({k: kwargs[k] for k in ("n", "r", "p", "dklen")})
        return real(password, **kwargs)

    monkeypatch.setattr(hashlib, "scrypt", spy)
    return calls


def test_absent_and_malformed_hashes_do_the_same_scrypt_work_as_a_real_check(hasher, stored, monkeypatch):
    calls = _spy(monkeypatch)
    hasher.verify("wrong password", stored)
    hasher.verify("wrong password", None)
    hasher.verify("wrong password", "scrypt$garbage")
    assert len(calls) == 3 and calls[0] == calls[1] == calls[2]


def test_weak_or_unbounded_configuration_is_refused():
    for params in ({"n": 2**10}, {"n": 3 * 2**13}, {"n": 2**21}, {"r": 0}, {"p": 0}, {"salt_bytes": 8}):
        with pytest.raises(ValueError):
            ScryptHasher(**params)


def test_tokens_are_long_urlsafe_and_unique():
    tokens = SecretsTokens()
    issued = {tokens.new_token() for _ in range(200)}
    assert len(issued) == 200
    alphabet = set(string.ascii_letters + string.digits + "-_")
    assert all(len(t) >= 43 and set(t) <= alphabet for t in issued)
