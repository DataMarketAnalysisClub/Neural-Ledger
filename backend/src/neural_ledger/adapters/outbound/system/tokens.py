"""Session tokens: 256 random bits, URL-safe. Only their sha256 digest is ever stored."""

from __future__ import annotations

import secrets


class SecretsTokens:
    def new_token(self) -> str:
        return secrets.token_urlsafe(32)
