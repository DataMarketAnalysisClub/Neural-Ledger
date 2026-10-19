"""Field encryption for the SQLite adapter (G11: Ley 21.719 art. 14 quinquies, ASVS V14).

Statements and transactions are stored as JSON payloads. Each payload is sealed with AES-256-GCM before it
is written and opened after it is read, so the database file, its WAL and any copy or backup of them hold
no description, merchant, amount or balance in clear. Ids, user ids and posting dates stay in clear
columns: the stores look rows up and order them by those.

The associated data binds a payload to its table and row (`statements|<user>|<id>`), so a sealed value
copied into another user's row, or from one table to another, fails to open instead of being read.

The key never lives in the database. It comes from NL_DATA_KEY (64 hex characters). Offline runs without
it get a random key in a file next to the database (`<db>.key`), so a copied database alone reads nothing;
live mode refuses to start without NL_DATA_KEY (bootstrap/container.py). Payloads written before G11 are
plain JSON and are still read, so an existing database keeps working; new writes are always sealed.
"""

from __future__ import annotations

import base64
import os
import secrets
from pathlib import Path

PREFIX = "nlenc1:"  # format version: AES-256-GCM, 12-byte nonce, base64(nonce || ciphertext || tag)
KEY_BYTES = 32
_NONCE_BYTES = 12


class FieldCipherError(Exception):
    """A payload could not be opened: wrong key, tampered value, or a value moved to another row."""


class WrongDataKey(FieldCipherError):
    """The configured key does not open what the database already holds (another key, or a migration not run)."""


class FieldCipher:
    def __init__(self, key: bytes) -> None:
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ImportError as exc:  # pragma: no cover - the api extra installs it
            raise RuntimeError("SQLite persistence encrypts its payloads and needs the `cryptography` package (api extra)") from exc
        if len(key) != KEY_BYTES:
            raise ValueError("the data key must be 32 bytes (NL_DATA_KEY: 64 hex characters)")
        self._aead = AESGCM(key)

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
    def is_current(stored: str) -> bool:
        """Sealed in the format seal() writes today (the migration rewrites older ones)."""
        return stored.startswith(PREFIX)

    def open(self, stored: str, aad: str) -> str:
        if not stored.startswith(PREFIX):
            return stored  # written before G11: plain JSON
        from cryptography.exceptions import InvalidTag

        raw = base64.b64decode(stored[len(PREFIX) :])
        try:
            return self._aead.decrypt(raw[:_NONCE_BYTES], raw[_NONCE_BYTES:], aad.encode("utf-8")).decode("utf-8")
        except InvalidTag:
            raise FieldCipherError(f"cannot open a payload sealed for {aad.split('|', 1)[0]}") from None
