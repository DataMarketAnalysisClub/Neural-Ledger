"""HMAC-SHA256 signer for authorizations. The secret comes from NL_HMAC_SECRET, never from the DB,
so someone who can edit stored terms cannot recompute a valid signature (test S05)."""

from __future__ import annotations

import hashlib
import hmac


class HmacSigner:
    def __init__(self, secret: str) -> None:
        if len(secret) < 16:
            raise ValueError("NL_HMAC_SECRET must be at least 16 characters")
        self._key = secret.encode("utf-8")

    def sign(self, message: str) -> str:
        return hmac.new(self._key, message.encode("utf-8"), hashlib.sha256).hexdigest()

    def verify(self, message: str, signature: str) -> bool:
        return hmac.compare_digest(self.sign(message), signature)
