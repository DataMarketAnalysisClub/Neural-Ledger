"""Typed user memory (ADR-048): the closed catalog mem-0.1 and the declarations the user confirmed.

Only declarations are stored. Whether statements support one (verified, conflict, matched paydays) is derived on read
by salary_check.py and never kept here. A declaration never becomes a contracted net salary and sets no amount by
itself: what it changes in the numbers is the domain's decision (ADR-049).

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


def _reference(field: str, value: object) -> None:
    """An identifier the declaration contract requires: a non-empty string (minLength 1), nothing more."""
    if not isinstance(value, str) or not value:
        raise InvalidInput(field, "must be a non-empty string")


@dataclass(frozen=True, slots=True)
class ChatOrigin:
    session_id: str
    message_id: str

    def __post_init__(self) -> None:
        _reference("origin.session_id", self.session_id)
        _reference("origin.message_id", self.message_id)


@dataclass(frozen=True, slots=True)
class ProfileOrigin:
    pass


@dataclass(frozen=True, slots=True)
class StatementOrigin:
    statement_id: str
    txn_id: str

    def __post_init__(self) -> None:
        _reference("origin.statement_id", self.statement_id)
        _reference("origin.txn_id", self.txn_id)


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
        _check_declaration(self)

    @property
    def effective_from(self) -> Month:
        return self.value.effective_from


def _check_declaration(d: Declaration) -> None:
    """What contracts/memory/declaration.schema.json requires of a stored version, plus an owner to bind it to.

    The constructor runs it, and check_appended runs it again on every declaration a store is about to write, so an
    object built around the constructor cannot reach either adapter.
    """
    for field in ("memory_id", "chain_id", "user_id", "audit_ref"):
        _reference(field, getattr(d, field))
    if d.confirmed_by != CONFIRMED_BY:
        raise InvalidInput("confirmed_by", "only the user confirms a declaration")
    if isinstance(d.version, bool) or not isinstance(d.version, int) or d.version < 1:
        raise InvalidInput("version", "versions start at 1")
    if not isinstance(d.confirmed_at, datetime) or d.confirmed_at.tzinfo is None or d.confirmed_at.utcoffset() is None:
        raise InvalidInput("confirmed_at", "must be a date-time with a time zone")
    if d.confirmed_at.utcoffset().total_seconds() % 60:
        raise InvalidInput("confirmed_at", "the offset must be whole minutes (RFC 3339)")
    if not isinstance(d.type, MemoryType) or not isinstance(d.source, Source):
        raise InvalidInput("declaration", "type and source must come from the catalog")
    if d.type is MemoryType.SALARY_NET and not isinstance(d.value, SalaryNet):
        raise InvalidInput("value", "must be a salary_net value")
    if not isinstance(d.origin, ChatOrigin | ProfileOrigin | StatementOrigin):
        raise InvalidInput("origin", "must be a chat, profile or statement reference")
    # A value or origin built around its own constructor is checked again by running that constructor.
    SalaryNet(d.value.amount, d.value.effective_from, d.value.net)
    if isinstance(d.origin, ChatOrigin):
        ChatOrigin(d.origin.session_id, d.origin.message_id)
    elif isinstance(d.origin, StatementOrigin):
        StatementOrigin(d.origin.statement_id, d.origin.txn_id)


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
    """The version that applied just before `version` took effect, for the previous salary level (ADR-049 §6)."""
    return applicable(declarations, version.effective_from.plus(-1))


def upcoming(declarations: Sequence[Declaration], pay_month: Month) -> Declaration | None:
    """The next version to take effect after a pay month, if one starts later."""
    later = [d for d in chain(declarations) if d.effective_from > pay_month]
    if not later:
        return None
    first = min(d.effective_from for d in later)
    return max((d for d in later if d.effective_from == first), key=lambda d: d.version)


def declaration_record(declaration: Declaration) -> dict:
    """A declaration as contracts/memory/declaration.schema.json shows it: no owner (authentication gives it)."""
    origin = declaration.origin
    if isinstance(origin, ChatOrigin):
        origin_record: dict = {"kind": "chat", "session_id": origin.session_id, "message_id": origin.message_id}
    elif isinstance(origin, StatementOrigin):
        origin_record = {"kind": "statement", "statement_id": origin.statement_id, "txn_id": origin.txn_id}
    else:
        origin_record = {"kind": "profile"}
    value = declaration.value
    return {
        "memory_id": declaration.memory_id,
        "chain_id": declaration.chain_id,
        "version": declaration.version,
        "catalog_version": CATALOG_VERSION,
        "value": {
            "type": declaration.type.value,
            "salary_net": {"amount": value.amount, "net": value.net, "effective_from": str(value.effective_from)},
        },
        "confirmed_at": declaration.confirmed_at.isoformat(),
        "confirmed_by": declaration.confirmed_by,
        "source": declaration.source.value,
        "origin": origin_record,
        "audit_ref": declaration.audit_ref,
    }


_RECORD_FIELDS = frozenset(
    {"memory_id", "chain_id", "version", "catalog_version", "value", "confirmed_at", "confirmed_by", "source", "origin", "audit_ref"}
)
_ORIGIN_FIELDS = {"chat": ("session_id", "message_id"), "profile": (), "statement": ("statement_id", "txn_id")}


def parse_declaration(raw: object, user_id: str) -> Declaration:
    """The inverse of declaration_record for a known owner; anything outside the catalog is refused."""
    if not isinstance(raw, Mapping) or set(raw) != _RECORD_FIELDS:
        raise InvalidInput("declaration", "must hold exactly the fields of a declaration")
    if raw["catalog_version"] != CATALOG_VERSION:
        raise InvalidInput("catalog_version", f"must be {CATALOG_VERSION}")
    value = raw["value"]
    if not isinstance(value, Mapping) or set(value) != {"type", "salary_net"} or value["type"] != MemoryType.SALARY_NET.value:
        raise InvalidInput("value", "must be a salary_net value")
    origin = raw["origin"]
    kind = origin.get("kind") if isinstance(origin, Mapping) else None
    if kind not in _ORIGIN_FIELDS or set(origin) != {"kind", *_ORIGIN_FIELDS[kind]}:
        raise InvalidInput("origin", "must be a chat, profile or statement reference")
    if any(not isinstance(origin[name], str) or not origin[name] for name in _ORIGIN_FIELDS[kind]):
        raise InvalidInput("origin", "references must be non-empty strings")
    parsed_origin: Origin = (
        ChatOrigin(origin["session_id"], origin["message_id"]) if kind == "chat"
        else StatementOrigin(origin["statement_id"], origin["txn_id"]) if kind == "statement"
        else ProfileOrigin()
    )
    try:
        confirmed_at = datetime.fromisoformat(raw["confirmed_at"])
        source = Source(raw["source"])
    except (TypeError, ValueError) as error:
        raise InvalidInput("declaration", "confirmed_at or source is malformed") from error
    for name in ("memory_id", "chain_id", "audit_ref"):
        if not isinstance(raw[name], str) or not raw[name]:
            raise InvalidInput(name, "must be a non-empty string")
    return Declaration(
        memory_id=raw["memory_id"], chain_id=raw["chain_id"], version=raw["version"], user_id=user_id,
        value=parse_salary_net(value["salary_net"]), confirmed_at=confirmed_at, source=source, origin=parsed_origin,
        audit_ref=raw["audit_ref"], confirmed_by=raw["confirmed_by"],
    )


def check_appended(declarations: Sequence[Declaration], expected_version: int) -> None:
    """A batch a store may append: one chain, owner and type, versions expected_version + 1, + 2, ... in order, and
    every declaration inside the contract. Raises ValueError otherwise; both adapters call it before any write."""
    if isinstance(expected_version, bool) or not isinstance(expected_version, int) or expected_version < 0:
        raise ValueError("expected_version must be 0 (a new chain) or the chain's last version")
    if not declarations:
        raise ValueError("nothing to append")
    for d in declarations:
        # Both adapters accept exactly what the SQLite codec reads back: a version that would not round-trip through
        # declaration_record / parse_declaration is refused here, before anything is written.
        try:
            _check_declaration(d)
            same = parse_declaration(declaration_record(d), d.user_id) == d
        except (InvalidInput, AttributeError, TypeError, ValueError) as error:
            raise ValueError(f"declaration outside the contract: {getattr(error, 'field', 'declaration')}") from error
        if not same:
            raise ValueError("declaration does not round-trip through its stored record")
    if len({(d.chain_id, d.user_id, d.type) for d in declarations}) != 1:
        raise ValueError("a batch appends to one chain of one owner and type")
    if [d.version for d in declarations] != list(range(expected_version + 1, expected_version + 1 + len(declarations))):
        raise ValueError("versions must follow the chain's last version, in order")
    if len({d.memory_id for d in declarations}) != len(declarations):
        raise ValueError("a memory_id appears twice in the batch")
