"""Calendar months. Pay cycles are labelled by the month whose spending they fund."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

_PATTERN = re.compile(r"^(\d{4})-(\d{2})$")


@dataclass(frozen=True, slots=True, order=True)
class Month:
    year: int
    month: int

    def __post_init__(self) -> None:
        if not 1 <= self.month <= 12:
            raise ValueError(f"month out of range: {self.month}")
        if not 1900 <= self.year <= 2200:
            raise ValueError(f"year out of range: {self.year}")

    @classmethod
    def parse(cls, text: str) -> Month:
        match = _PATTERN.match(text.strip())
        if not match:
            raise ValueError(f"expected YYYY-MM, got {text!r}")
        return cls(int(match.group(1)), int(match.group(2)))

    @classmethod
    def of(cls, day: date) -> Month:
        return cls(day.year, day.month)

    def plus(self, months: int) -> Month:
        index = self.year * 12 + (self.month - 1) + months
        return Month(index // 12, index % 12 + 1)

    def months_until(self, other: Month) -> int:
        """Signed number of months from self to other."""
        return (other.year - self.year) * 12 + (other.month - self.month)

    def first_day(self) -> date:
        return date(self.year, self.month, 1)

    def __str__(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"


def month_range(start: Month, count: int) -> tuple[Month, ...]:
    return tuple(start.plus(i) for i in range(count))
