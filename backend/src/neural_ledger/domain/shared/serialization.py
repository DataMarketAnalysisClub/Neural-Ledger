"""Convert domain objects to JSON-safe primitives (dicts, lists, str, int, float, bool, None)."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from fractions import Fraction
from typing import Any

from .month import Month


def to_primitive(value: Any) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (int, str)):
        return value
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, (Fraction, Decimal)):
        return round(float(value), 6)
    if isinstance(value, Month):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: to_primitive(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, Mapping):
        return {_key(k): to_primitive(v) for k, v in value.items()}
    if isinstance(value, (set, frozenset)):
        return sorted(to_primitive(v) for v in value)
    if isinstance(value, (list, tuple)):
        return [to_primitive(v) for v in value]
    raise TypeError(f"cannot serialize {type(value).__name__}")


def _key(key: Any) -> str:
    primitive = to_primitive(key)
    return primitive if isinstance(primitive, str) else str(primitive)
