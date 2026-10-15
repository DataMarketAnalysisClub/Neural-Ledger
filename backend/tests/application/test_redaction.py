"""StatementRedactor (ADR-028): the domain rules always run, a detector can only add masking, and when the detector
is unavailable the rules alone redact the statement and the report says so. Every name and number is fictional."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from neural_ledger.adapters.outbound.privacy.null import NullDetector
from neural_ledger.application.ports import DetectorUnavailable, PersonalDataDetector
from neural_ledger.application.services.prompts import SYSTEM_PROMPT
from neural_ledger.application.services.redaction import RedactionReport, StatementRedactor
from neural_ledger.domain.privacy.redaction import PLACEHOLDER_CODES, REDACTION_VERSION, Placeholder, Span
from neural_ledger.domain.statements.model import BankStatement, DailyBalance, StatementLine, StatementSummary, reconcile

STATEMENT = BankStatement(
    bank="test",
    account_ref="0-000-00-12345-6",
    currency="CLP",
    period_start=date(2026, 9, 1),
    period_end=date(2026, 9, 30),
    lines=(
        StatementLine(0, date(2026, 9, 2), "0000000003 Transf a JUAN PEREZ 11.111.111-1", -40_000, "2441010", "401", 0.91),
        StatementLine(1, date(2026, 9, 2), "Compra Nacional MD JUMBO CONCEPCION", -12_990, "2441011", "401"),
        StatementLine(2, date(2026, 9, 3), "PAGO A MARIA SOTO", -5_000, None, "90"),  # a name outside a transfer: rules miss it
    ),
    summary=StatementSummary(100_000, 57_990, 0, 42_010),
    daily_balances=(DailyBalance(date(2026, 9, 3), 42_010),),
    statement_number="77",
    source="ocr",
)
RULES_ONLY = ["[NUMBER] Transf a [PERSON] [ID]", "Compra Nacional MD JUMBO CONCEPCION", "PAGO A MARIA SOTO"]
MARIA_SOTO = Span(7, 17, Placeholder.PERSON)


class FixedDetector:
    """Answers what the test says and records what it was sent."""

    name = "fixed"

    def __init__(self, answer) -> None:
        self.answer = answer
        self.sent: list[list[str]] = []

    def detect(self, texts):
        self.sent.append(list(texts))
        return self.answer


class DownDetector:
    name = "down"

    def detect(self, texts):
        raise DetectorUnavailable("HTTP 503")


class BuggyDetector:
    name = "buggy"

    def detect(self, texts):
        raise RuntimeError("an adapter bug")


def _descriptions(statement: BankStatement) -> list[str]:
    return [line.description for line in statement.lines]


def test_the_rules_mask_descriptions_and_the_account_and_keep_every_amount():
    clean, report = StatementRedactor(NullDetector()).redact(STATEMENT)
    assert _descriptions(clean) == RULES_ONLY
    assert clean.account_ref == "****3456"
    # Everything but the descriptions and the account is kept as read, so reconciliation sees the same statement.
    lines = tuple(replace(line, description=text) for line, text in zip(STATEMENT.lines, RULES_ONLY))
    assert clean == replace(STATEMENT, account_ref="****3456", lines=lines)
    assert reconcile(clean) == reconcile(STATEMENT)
    counts = ((Placeholder.PERSON, 1), (Placeholder.ID, 1), (Placeholder.NUMBER, 1))
    assert report == RedactionReport(REDACTION_VERSION, "none", False, counts) and report.masked == 3


def test_a_detector_adds_what_the_rules_miss():
    detector = FixedDetector([(), (), (MARIA_SOTO,)])
    clean, report = StatementRedactor(detector).redact(STATEMENT)
    assert _descriptions(clean)[2] == "PAGO A [PERSON]"
    assert detector.sent == [[line.description for line in STATEMENT.lines]]  # the raw text, in memory, once
    assert (report.detector, report.degraded, dict(report.counts)[Placeholder.PERSON]) == ("fixed", False, 2)


def test_a_detector_cannot_remove_masking_and_overlaps_become_one_placeholder():
    nothing = StatementRedactor(FixedDetector([(), (), ()])).redact(STATEMENT)[0]
    assert _descriptions(nothing) == RULES_ONLY
    overlapping = Span(18, 33, Placeholder.PERSON)  # "a JUAN PEREZ 11": over the rules' name and into the RUT
    clean, report = StatementRedactor(FixedDetector([(overlapping,), (), ()])).redact(STATEMENT)
    assert _descriptions(clean)[0] == "[NUMBER] Transf [ID]"
    assert report.masked == 2


def test_an_unavailable_detector_leaves_the_rules_and_flags_the_import_degraded(caplog):
    with caplog.at_level("WARNING"):
        clean, report = StatementRedactor(DownDetector()).redact(STATEMENT)
    assert _descriptions(clean) == RULES_ONLY and clean.account_ref == "****3456"
    assert (report.detector, report.degraded, report.masked) == ("down", True, 3)
    assert "down unavailable" in caplog.text and "HTTP 503" in caplog.text
    assert "JUAN" not in caplog.text and "MARIA" not in caplog.text


@pytest.mark.parametrize(
    "answer",
    [
        [(), ()],  # one answer missing
        [(), (), (Span(7, 99, Placeholder.PERSON),)],  # a span past the end of its text
        [(), (), ((7, 17, "PERSON"),)],  # not a Span
    ],
)
def test_an_answer_that_does_not_fit_the_text_counts_as_unavailable(answer):
    clean, report = StatementRedactor(FixedDetector(answer)).redact(STATEMENT)
    assert _descriptions(clean) == RULES_ONLY and report.degraded


def test_any_other_detector_error_propagates_so_the_import_fails_closed():
    with pytest.raises(RuntimeError, match="an adapter bug"):
        StatementRedactor(BuggyDetector()).redact(STATEMENT)


def test_the_null_detector_is_an_offline_personal_data_detector_that_finds_nothing():
    detector = NullDetector()
    assert isinstance(detector, PersonalDataDetector) and detector.name == "none"
    assert detector.detect(["Transf a JUAN PEREZ", "JUMBO"]) == ((), ())
    assert StatementRedactor(detector).detector == "none"


def test_the_agent_is_told_that_placeholders_mark_hidden_data_it_must_not_guess():
    assert all(f"[{code}]" in SYSTEM_PROMPT for code in PLACEHOLDER_CODES)
    assert "removed on purpose" in SYSTEM_PROMPT and "Never guess" in SYSTEM_PROMPT
    assert '{"untrusted_text": "..."}' in SYSTEM_PROMPT  # the f-string kept the literal braces
