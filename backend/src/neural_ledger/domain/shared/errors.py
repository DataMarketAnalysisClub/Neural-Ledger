"""Domain errors. Use cases translate them into envelopes; adapters translate envelopes into HTTP."""

from __future__ import annotations


class DomainError(Exception):
    """Base class for rule violations."""


class InvalidInput(DomainError):
    """An input outside the contract. Becomes an INVALID_INPUT envelope; no engine runs."""

    def __init__(self, field: str, message: str, allowed: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.field = field
        self.message = message
        self.allowed = allowed


class InsufficientData(DomainError):
    """Unknown or incomplete state (hard rule H4). Becomes an INSUFFICIENT_DATA envelope; no guess is made."""

    def __init__(self, missing: tuple[str, ...], message: str) -> None:
        super().__init__(message)
        self.missing = tuple(missing)
        self.message = message
