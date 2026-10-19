"""Typed user memory (ADR-047): the closed catalog mem-0.1 and the declarations the user confirmed.

Only declarations are stored. Whether statements support one (verified, conflict, matched paydays) is derived on read
by salary_check.py and never kept here. A declaration never becomes a contracted net salary and sets no amount by
itself: what it changes in the numbers is the domain's decision (ADR-040).

Versions: editing or re-confirming appends a version to the chain. A version applies to pay months from its
`effective_from` until the next `effective_from` in the chain; of two versions with the same `effective_from`, the
later one supersedes the earlier. A version that starts later leaves earlier months to the previous one.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from ..shared.errors import InvalidInput
from ..shared.month import Month

CATALOG_VERSION = "mem-0.1"
MAX_SALARY_NET = 100_000_000  # CLP; contracts/memory/memory_value.schema.json (salary_net.amount.maximum)
CONFIRMED_BY = "user"  # only the user confirms a declaration; no tool and no model does


class MemoryType(str, Enum):
    SALARY_NET = "salary_net"


class Source(str, Enum):
    CHAT = "chat"
    PROFILE = "profile"


@dataclass(frozen=True, slots=True)
class SalaryNet:
    """The user's net salary (líquido), declared from the pay month whose payday first credits it."""

    amount: int
    effective_from: Month
    net: bool = True

    def __post_init__(self) -> None:
        if isinstance(self.amount, bool) or not isinstance(self.amount, int) or not 1 <= self.amount <= MAX_SALARY_NET:
            raise InvalidInput("salary_net.amount", f"must be an integer CLP amount from 1 to {MAX_SALARY_NET}")
        if self.net is not True:
            raise InvalidInput("salary_net.net", "only a net salary is declared")
        if not isinstance(self.effective_from, Month):
            raise InvalidInput("salary_net.effective_from", "must be a pay month (YYYY-MM)")


@dataclass(frozen=True, slots=True)
class ChatOrigin:
    session_id: str
    message_id: str


@dataclass(frozen=True, slots=True)
class ProfileOrigin:
    pass


@dataclass(frozen=True, slots=True)
class StatementOrigin:
    statement_id: str
    txn_id: str


Origin = ChatOrigin | ProfileOrigin | StatementOrigin


@dataclass(frozen=True, slots=True)
class Declaration:
    """One stored version of a chain. The origin is a reference; memory keeps neither the message nor its hash."""

    memory_id: str
    chain_id: str
    version: int
    user_id: str
    value: SalaryNet
    confirmed_at: datetime
    source: Source
    origin: Origin
    audit_ref: str
    confirmed_by: str = CONFIRMED_BY
    type: MemoryType = MemoryType.SALARY_NET

    def __post_init__(self) -> None:
        if self.confirmed_by != CONFIRMED_BY:
            raise InvalidInput("confirmed_by", "only the user confirms a declaration")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise InvalidInput("version", "versions start at 1")
        if self.confirmed_at.tzinfo is None:
            raise InvalidInput("confirmed_at", "must carry a time zone")

    @property
    def effective_from(self) -> Month:
        return self.value.effective_from


def parse_salary_net(raw: object) -> SalaryNet:
    """A salary_net value from JSON (a body or the store): unknown fields, booleans and other types are refused."""
    if not isinstance(raw, Mapping):
        raise InvalidInput("salary_net", "must be an object")
    unknown = set(raw) - {"amount", "net", "effective_from"}
    if unknown:
        raise InvalidInput(f"salary_net.{sorted(unknown)[0]}", "unknown field")
    for name in ("amount", "net", "effective_from"):
        if name not in raw:
            raise InvalidInput(f"salary_net.{name}", "is required")
    effective_from = raw["effective_from"]
    if not isinstance(effective_from, str):
        raise InvalidInput("salary_net.effective_from", "must be a pay month (YYYY-MM)")
    try:
        month = Month.parse(effective_from)
    except ValueError as error:
        raise InvalidInput("salary_net.effective_from", "must be a pay month (YYYY-MM)") from error
    return SalaryNet(raw["amount"], month, raw["net"])


def chain(declarations: Sequence[Declaration]) -> tuple[Declaration, ...]:
    """One chain's versions in version order; mixing chains, owners or repeated versions is refused."""
    ordered = tuple(sorted(declarations, key=lambda d: d.version))
    if len({(d.chain_id, d.user_id) for d in ordered}) > 1:
        raise ValueError("declarations of more than one chain or owner")
    if len({d.version for d in ordered}) != len(ordered):
        raise ValueError("a version appears twice in the chain")
    return ordered


def applicable(declarations: Sequence[Declaration], pay_month: Month) -> Declaration | None:
    """The version that applies to a pay month: the latest `effective_from` on or before it, then the latest version."""
    candidates = [d for d in chain(declarations) if d.effective_from <= pay_month]
    return max(candidates, key=lambda d: (d.effective_from, d.version)) if candidates else None


def previous(declarations: Sequence[Declaration], version: Declaration) -> Declaration | None:
    """The version that applied just before `version` took effect, for the previous salary level (ADR-040 §6)."""
    return applicable(declarations, version.effective_from.plus(-1))


def upcoming(declarations: Sequence[Declaration], pay_month: Month) -> Declaration | None:
    """The next version to take effect after a pay month, if one starts later."""
    later = [d for d in chain(declarations) if d.effective_from > pay_month]
    if not later:
        return None
    first = min(d.effective_from for d in later)
    return max((d for d in later if d.effective_from == first), key=lambda d: d.version)
