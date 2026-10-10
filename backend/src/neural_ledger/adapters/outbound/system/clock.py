"""Clock adapters. The demo runs on a fixed clock so every scene is reproducible."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FixedClock:
    def __init__(self, instant: datetime) -> None:
        if instant.tzinfo is None:
            raise ValueError("FixedClock needs a timezone-aware datetime")
        self._now = instant

    def now(self) -> datetime:
        return self._now

    def advance(self, **delta: float) -> None:
        self._now = self._now + timedelta(**delta)
