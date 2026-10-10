"""Id generators."""

from __future__ import annotations

import itertools
import threading
import uuid


class UuidIds:
    def new(self, prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex}"


class SequentialIds:
    """Deterministic ids for tests and recorded demos."""

    def __init__(self) -> None:
        self._counter = itertools.count(1)
        self._lock = threading.Lock()

    def new(self, prefix: str) -> str:
        with self._lock:
            return f"{prefix}_{next(self._counter):06d}"
