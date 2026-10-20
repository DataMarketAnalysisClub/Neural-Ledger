"""The memory consent and the counters that make cached memory obsolete (ADR-048 §6).

One state per user: the consent (missing until first granted), a consent generation and a memory revision. The
generation grows by one on every actual change of the consent and never on a repeated update. The revision grows
whenever a declaration is confirmed or a chain is deleted and is never reset: a chain deleted and created again keeps
counting from where the user was. A proposal captures both, so a change of either makes it stale, and consenting
again never revives it.

Revoking keeps the declarations (the user may still read, export or delete them) but stops every use of them.
Revoking a consent never granted leaves it missing: there was nothing to revoke.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

from ..shared.errors import InvalidInput


class Consent(str, Enum):
    MISSING = "missing"
    GRANTED = "granted"
    REVOKED = "revoked"


def _counter(field: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvalidInput(field, "must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class MemoryState:
    user_id: str
    consent: Consent = Consent.MISSING
    consent_generation: int = 0
    memory_revision: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.user_id, str) or not self.user_id:
            raise InvalidInput("user_id", "must be a non-empty string")
        if not isinstance(self.consent, Consent):
            raise InvalidInput("consent", "must be missing, granted or revoked")
        _counter("consent_generation", self.consent_generation)
        _counter("memory_revision", self.memory_revision)

    @property
    def granted(self) -> bool:
        return self.consent is Consent.GRANTED


def parse_consent_update(raw: object) -> Consent:
    """The consent a PUT asks for: granted or revoked; missing is never requested."""
    if not isinstance(raw, str) or raw not in (Consent.GRANTED.value, Consent.REVOKED.value):
        raise InvalidInput("consent", "must be granted or revoked", (Consent.GRANTED.value, Consent.REVOKED.value))
    return Consent(raw)


def with_consent(state: MemoryState, requested: Consent) -> MemoryState:
    """The state after a consent update; the same state when it changes nothing (idempotent)."""
    if requested is Consent.MISSING:
        raise ValueError("consent is granted or revoked, never set back to missing")
    if requested is state.consent or (requested is Consent.REVOKED and state.consent is Consent.MISSING):
        return state
    return replace(state, consent=requested, consent_generation=state.consent_generation + 1)


def with_memory_change(state: MemoryState) -> MemoryState:
    """The state after a confirmed declaration or a deleted chain."""
    return replace(state, memory_revision=state.memory_revision + 1)


def state_record(state: MemoryState) -> dict:
    return {"consent": state.consent.value, "consent_generation": state.consent_generation, "memory_revision": state.memory_revision}


def parse_state(raw: object, user_id: str) -> MemoryState:
    if not isinstance(raw, dict) or set(raw) != {"consent", "consent_generation", "memory_revision"}:
        raise InvalidInput("memory_state", "must hold exactly consent, consent_generation and memory_revision")
    try:
        consent = Consent(raw["consent"])
    except ValueError as error:
        raise InvalidInput("consent", "must be missing, granted or revoked") from error
    return MemoryState(user_id, consent, raw["consent_generation"], raw["memory_revision"])
