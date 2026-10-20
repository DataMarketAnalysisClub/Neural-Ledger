"""Field encryption for the SQLite adapter (G11: Ley 21.719 art. 14 quinquies, ASVS V14).

Every payload that holds personal or financial data is sealed with AES-256-GCM before it is written and opened
after it is read: statements, transactions, profiles (questionnaire answers), accounts (email, password hash),
proposals, authorizations, savings rules, declared memory (ADR-048) and audit records. The database file, its WAL and any copy or backup of
them hold none of it in clear. Ids, user ids, the session token digest and transaction posting dates stay in
clear columns: the stores look rows up and order them by those.

Key hierarchy. NL_DATA_KEY (32 bytes, 64 hex characters) is never used directly. HKDF-SHA256 derives one subkey
per purpose from it, with a distinct `info` string:
- the field key (`neural-ledger/v2/field-encryption`) seals and opens payloads;
- the email index key (`neural-ledger/v1/blind-index/email`) computes HMAC-SHA256 of the normalized email, the
  only email column the database can search. It finds an account without storing the address; without the key,
  an index value cannot be checked against a guessed address.

The associated data binds a payload to its table, owner and row (`statements|<user>|<id>`), so a sealed value
copied into another user's row, or from one table to another, fails to open instead of being read.

Formats: `nlenc2:` (current, field key) and `nlenc1:` (G11 before option B: NL_DATA_KEY itself as the AES key),
which is still opened and is rewritten by the migration. A value that is not sealed is refused: the migration
(sqlite_migration.py) seals any plain text left from before, so plain text in a current database can only be an
edit made around the application.

The key never lives in the database: bootstrap/data_key.py says where it comes from.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
import secrets
from pathlib import Path

PREFIX = "nlenc2:"  # format version: AES-256-GCM under the derived field key, 12-byte nonce, base64(nonce || ciphertext || tag)
LEGACY_PREFIX = "nlenc1:"  # the same, under NL_DATA_KEY itself (before option B)
KEY_BYTES = 32
_NONCE_BYTES = 12
FIELD_INFO = b"neural-ledger/v2/field-encryption"
INDEX_INFO = b"neural-ledger/v1/blind-index/"
INDEX_PURPOSES = ("email",)


class FieldCipherError(Exception):
    """A payload could not be opened: wrong key, tampered value, or a value moved to another row."""


class WrongDataKey(FieldCipherError):
    """The configured key does not open what the database already holds (another key, or a migration not run)."""


def derive(key: bytes, info: bytes) -> bytes:
    """HKDF-SHA256 (RFC 5869) without salt: one independent 32-byte subkey per purpose of the data key."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    return HKDF(algorithm=hashes.SHA256(), length=KEY_BYTES, salt=None, info=info).derive(key)


class FieldCipher:
    def __init__(self, key: bytes) -> None:
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ImportError as exc:  # pragma: no cover - the api extra installs it
            raise RuntimeError("SQLite persistence encrypts its payloads and needs the `cryptography` package (api extra)") from exc
        if len(key) != KEY_BYTES:
            raise ValueError("the data key must be 32 bytes (NL_DATA_KEY: 64 hex characters)")
        self._aead = AESGCM(derive(key, FIELD_INFO))
        self._legacy = AESGCM(key)  # opens nlenc1 values only; never seals
        self._index_keys = {purpose: derive(key, INDEX_INFO + purpose.encode("ascii")) for purpose in INDEX_PURPOSES}

    @classmethod
    def from_hex(cls, value: str) -> FieldCipher:
        try:
            key = bytes.fromhex(value.strip())
        except ValueError:
            raise ValueError("NL_DATA_KEY must be 64 hex characters") from None
        return cls(key)

    @classmethod
    def from_key_file(cls, path: str | Path) -> FieldCipher:
        """Reads the key file, creating it (owner-only where the OS allows) on first use."""
        path = Path(path)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="ascii") as handle:
                handle.write(secrets.token_hex(KEY_BYTES))
        return cls.from_hex(path.read_text(encoding="ascii"))

    def seal(self, plaintext: str, aad: str) -> str:
        nonce = secrets.token_bytes(_NONCE_BYTES)
        sealed = self._aead.encrypt(nonce, plaintext.encode("utf-8"), aad.encode("utf-8"))
        return PREFIX + base64.b64encode(nonce + sealed).decode("ascii")

    @staticmethod
    def is_sealed(stored: object) -> bool:
        return isinstance(stored, str) and stored.startswith((PREFIX, LEGACY_PREFIX))

    @staticmethod
    def is_current(stored: str) -> bool:
        """Sealed in the format seal() writes today (the migration rewrites older ones)."""
        return stored.startswith(PREFIX)

    def open(self, stored: str, aad: str) -> str:
        from cryptography.exceptions import InvalidTag

        what = aad.split("|", 1)[0]
        if stored.startswith(PREFIX):
            aead, body = self._aead, stored[len(PREFIX) :]
        elif stored.startswith(LEGACY_PREFIX):
            aead, body = self._legacy, stored[len(LEGACY_PREFIX) :]
        else:
            raise FieldCipherError(f"a {what} value is stored in clear; run `neural-ledger migrate-data`")
        try:
            raw = base64.b64decode(body, validate=True)
            return aead.decrypt(raw[:_NONCE_BYTES], raw[_NONCE_BYTES:], aad.encode("utf-8")).decode("utf-8")
        except (InvalidTag, binascii.Error, ValueError):
            raise FieldCipherError(f"cannot open a payload sealed for {what}") from None

    def blind_index(self, purpose: str, value: str) -> str:
        """HMAC-SHA256 of value under the purpose's derived key, hex. Equal inputs give equal outputs (searchable)."""
        return hmac.new(self._index_keys[purpose], value.encode("utf-8"), hashlib.sha256).hexdigest()
