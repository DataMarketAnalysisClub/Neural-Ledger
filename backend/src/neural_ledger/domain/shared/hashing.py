"""Canonical JSON and content ids. Same input always gives the same id (reproducibility)."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .serialization import to_primitive


def canonical_json(value: Any) -> str:
    return json.dumps(to_primitive(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def content_id(prefix: str, *parts: Any) -> str:
    return f"{prefix}_{sha256_hex(canonical_json(list(parts)))[:16]}"
