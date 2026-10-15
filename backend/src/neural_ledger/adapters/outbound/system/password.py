"""scrypt password hashing (standard library). Stored form: scrypt$n$r$p$<base64 salt>$<base64 key>.

verify() without a stored hash (no such account) or with a malformed one runs the same scrypt work
on a dummy hash made with the configured parameters, so the time taken does not reveal whether an
account exists. Parameters read back from storage are bounded, so a tampered row cannot ask for
unbounded memory. There is no weaker setting: the configuration floor is the default cost.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets

SCHEME = "scrypt"
MIN_N, MAX_N = 2**14, 2**20
MAX_R, MAX_P = 16, 16
MIN_SALT, MAX_SALT = 16, 64
MIN_KEY, MAX_KEY = 16, 64
MAXMEM = 128 * 1024 * 1024


def _bounded(n: int, r: int, p: int) -> bool:
    return (
        MIN_N <= n <= MAX_N and n & (n - 1) == 0
        and 1 <= r <= MAX_R and 1 <= p <= MAX_P
        and 128 * r * (n + p + 2) <= MAXMEM
    )


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"), validate=True)


def _int(text: str) -> int:
    if not (text.isascii() and text.isdigit()):
        raise ValueError("not a decimal number")
    return int(text)


class ScryptHasher:
    def __init__(self, n: int = 2**14, r: int = 8, p: int = 1, dklen: int = 32, salt_bytes: int = 16) -> None:
        if not _bounded(n, r, p) or not MIN_KEY <= dklen <= MAX_KEY or not MIN_SALT <= salt_bytes <= MAX_SALT:
            raise ValueError("scrypt parameters out of bounds")
        self._n, self._r, self._p, self._dklen, self._salt_bytes = n, r, p, dklen, salt_bytes
        self._dummy = self._parse(self.hash(secrets.token_urlsafe(16)))

    def hash(self, password: str) -> str:
        salt = secrets.token_bytes(self._salt_bytes)
        key = self._derive(password, salt, self._n, self._r, self._p, self._dklen)
        return f"{SCHEME}${self._n}${self._r}${self._p}${_b64(salt)}${_b64(key)}"

    def verify(self, password: str, encoded: str | None) -> bool:
        parsed = self._parse(encoded) if encoded is not None else None
        n, r, p, salt, expected = parsed or self._dummy
        key = self._derive(password, salt, n, r, p, len(expected))
        return hmac.compare_digest(key, expected) and parsed is not None

    @staticmethod
    def _derive(password: str, salt: bytes, n: int, r: int, p: int, dklen: int) -> bytes:
        secret = password.encode("utf-8", "surrogatepass")
        return hashlib.scrypt(secret, salt=salt, n=n, r=r, p=p, dklen=dklen, maxmem=MAXMEM)

    @staticmethod
    def _parse(encoded: str) -> tuple[int, int, int, bytes, bytes] | None:
        parts = encoded.split("$") if isinstance(encoded, str) else []
        if len(parts) != 6 or parts[0] != SCHEME:
            return None
        try:
            n, r, p = (_int(part) for part in parts[1:4])
            salt, key = _unb64(parts[4]), _unb64(parts[5])
        except (ValueError, binascii.Error):
            return None
        if not _bounded(n, r, p) or not MIN_SALT <= len(salt) <= MAX_SALT or not MIN_KEY <= len(key) <= MAX_KEY:
            return None
        return n, r, p, salt, key
