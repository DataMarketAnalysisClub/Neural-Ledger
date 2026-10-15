"""Remove personal data from a statement as it is imported, before anything stores, classifies or audits it (ADR-028).

Two layers. The domain rules always run and are the floor. The detector (a port, `none` by default) runs after them
and can only add spans. If the detector is unavailable, or answers something that does not fit the text, the rules
alone redact the statement and the report says it is degraded. Any other error propagates, so the import fails
closed: nothing is stored.

Only the descriptions and the account reference carry personal data. Amounts, dates, the bank's document number and
the branch code stay as read, so reconciliation and the statement id are unaffected.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, replace

from ...domain.privacy.redaction import REDACTION_VERSION, Placeholder, Span, apply, find_spans, mask_account, merge_spans
from ...domain.statements.model import BankStatement
from ..ports import DetectorUnavailable, PersonalDataDetector

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RedactionReport:
    """How one statement was redacted. Counts only: it never holds any of the text it masked."""

    rules: str  # REDACTION_VERSION of the domain rules
    detector: str  # the detector configured after the rules; "none" when the rules run alone
    degraded: bool  # the detector was unavailable, so only the rules ran
    counts: tuple[tuple[Placeholder, int], ...]  # placeholders inserted per category, in Placeholder order, zeros left out

    @property
    def masked(self) -> int:
        return sum(count for _, count in self.counts)


class StatementRedactor:
    def __init__(self, detector: PersonalDataDetector) -> None:
        self._detector = detector

    @property
    def detector(self) -> str:
        return self._detector.name

    def redact(self, statement: BankStatement) -> tuple[BankStatement, RedactionReport]:
        """The statement with placeholders in its descriptions and a masked account, and how it was done."""
        texts = [line.description for line in statement.lines]
        detected, degraded = self._detect(texts)
        spans = [merge_spans((*find_spans(text), *extra)) for text, extra in zip(texts, detected, strict=True)]
        lines = tuple(replace(line, description=apply(line.description, found)) for line, found in zip(statement.lines, spans, strict=True))
        counts = Counter(span.category for found in spans for span in found)
        report = RedactionReport(REDACTION_VERSION, self._detector.name, degraded, tuple((c, counts[c]) for c in Placeholder if counts[c]))
        return replace(statement, account_ref=mask_account(statement.account_ref), lines=lines), report

    def _detect(self, texts: Sequence[str]) -> tuple[list[tuple[Span, ...]], bool]:
        """The detector's spans per text, or none at all (degraded) when it cannot give a usable answer."""
        try:
            detected = [tuple(found) for found in self._detector.detect(texts)]
            if len(detected) != len(texts):
                raise DetectorUnavailable(f"answered for {len(detected)} of {len(texts)} texts")
            if any(not isinstance(span, Span) or span.end > len(text) for text, found in zip(texts, detected) for span in found):
                raise DetectorUnavailable("returned a span outside its text")
        except DetectorUnavailable as exc:
            # The reason only: a detector's errors never carry statement text (PersonalDataDetector contract).
            logger.warning("personal-data detector %s unavailable, statement redacted by the rules only: %s", self._detector.name, exc)
            return [() for _ in texts], True
        return detected, False
