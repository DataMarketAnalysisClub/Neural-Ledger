"""The response envelope every financial tool returns (contracts/common/envelope.schema.json).

Every number the agent may say must appear in `facts`; every assumption it must
mention appears in `warnings`. The response verifier checks explanations against both.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Generic, TypeVar

T = TypeVar("T")


class Status(str, Enum):
    OK = "OK"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    INVALID_INPUT = "INVALID_INPUT"


@dataclass(frozen=True, slots=True)
class Fact:
    """A traceable number: what it is, its value, its unit and how it was derived."""

    key: str
    value: int | float | str
    unit: str
    derivation: str


@dataclass(frozen=True, slots=True)
class Caveat:
    """An assumption the explanation must mention. Serialized under `warnings`.

    `must_mention` lists tokens; an explanation mentions the caveat if it contains any of them.
    """

    code: str
    message: str
    must_mention: tuple[str, ...] = ()


@dataclass(frozen=True)
class Envelope(Generic[T]):
    status: Status
    params_version: str
    data: T | None = None
    snapshot_id: str | None = None
    as_of: str | None = None
    facts: tuple[Fact, ...] = ()
    warnings: tuple[Caveat, ...] = ()
    missing: tuple[str, ...] = ()
    field: str | None = None
    allowed: tuple[str, ...] = ()
    message: str | None = None

    @property
    def ok(self) -> bool:
        return self.status is Status.OK

    @staticmethod
    def success(
        data: T,
        *,
        params_version: str,
        snapshot_id: str,
        as_of: str,
        facts: tuple[Fact, ...] = (),
        warnings: tuple[Caveat, ...] = (),
    ) -> Envelope[T]:
        return Envelope(
            status=Status.OK,
            params_version=params_version,
            data=data,
            snapshot_id=snapshot_id,
            as_of=as_of,
            facts=facts,
            warnings=warnings,
        )

    @staticmethod
    def insufficient(missing: tuple[str, ...], *, params_version: str, message: str) -> Envelope[T]:
        return Envelope(
            status=Status.INSUFFICIENT_DATA,
            params_version=params_version,
            missing=missing,
            message=message,
        )

    @staticmethod
    def invalid(field: str, allowed: tuple[str, ...], *, params_version: str, message: str) -> Envelope[T]:
        return Envelope(
            status=Status.INVALID_INPUT,
            params_version=params_version,
            field=field,
            allowed=allowed,
            message=message,
        )
