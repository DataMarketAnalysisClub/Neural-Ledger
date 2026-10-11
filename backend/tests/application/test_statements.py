"""Statement import end to end (container wiring, synthetic cartola): read → reconcile → store → audit."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from neural_ledger.adapters.outbound.persistence.memory import InMemoryAuditLog, InMemoryStatementStore
from neural_ledger.adapters.outbound.system.clock import FixedClock
from neural_ledger.adapters.outbound.system.ids import SequentialIds
from neural_ledger.application.ports import StatementReaderUnavailable, StatementUnreadable
from neural_ledger.application.use_cases.statements import StatementUseCases
from neural_ledger.domain.audit.events import AuditKind
from neural_ledger.domain.shared.envelope import Status
from tests.statement_samples import Sample, santander_pdf

pytest.importorskip("pymupdf")
pytest.importorskip("pdfplumber")


def test_import_stores_a_verified_statement_and_audits_it(services):
    result = services.statements.import_statement("camila", santander_pdf())
    assert result.status is Status.OK
    assert result.data.duplicate is False
    summary = result.data.statement
    assert summary.verified and summary.issues == ()
    assert (summary.line_count, summary.total_debits, summary.total_credits) == (7, 61_080, 463_521)
    assert result.warnings == ()
    assert {f.key.rsplit(".", 1)[1]: f.value for f in result.facts}["closing_balance"] == 1_402_441

    listed = services.statements.list_statements("camila").data
    assert [s.statement_id for s in listed] == [summary.statement_id]
    events = [e for e in services.audit.raw() if e.draft.kind is AuditKind.STATEMENT_IMPORTED]
    assert len(events) == 1 and events[0].draft.execution_result == "VERIFIED" and events[0].draft.user_id == "camila"


def test_reimport_is_a_duplicate_and_stores_nothing_new(services):
    first = services.statements.import_statement("camila", santander_pdf())
    again = services.statements.import_statement("camila", santander_pdf())
    assert again.data.duplicate is True
    assert again.data.statement.statement_id == first.data.statement.statement_id
    assert [w.code for w in again.warnings] == ["DUPLICATE_STATEMENT"]
    assert len(services.statements.list_statements("camila").data) == 1


def test_statement_that_does_not_add_up_is_stored_unverified_with_a_warning(services):
    result = services.statements.import_statement("camila", santander_pdf(Sample(daily_override={"04/12": 1_154_942})))
    assert result.status is Status.OK
    assert result.data.statement.verified is False
    assert {i.code for i in result.data.statement.issues} == {"DAILY_BALANCE"}
    (warning,) = result.warnings
    assert warning.code == "STATEMENT_UNVERIFIED" and "DAILY_BALANCE" in warning.message

    detail = services.statements.get_statement("camila", result.data.statement.statement_id)
    assert [w.code for w in detail.warnings] == ["STATEMENT_UNVERIFIED"]


def test_detail_wraps_descriptions_as_untrusted_and_is_scoped_to_the_owner(services):
    statement_id = services.statements.import_statement("camila", santander_pdf()).data.statement.statement_id
    detail = services.statements.get_statement("camila", statement_id).data
    assert detail.lines[0].description == {"untrusted_text": "Compra Nacional MD SHOP ONE"}
    assert detail.lines[0].amount == -3_280
    assert services.statements.get_statement("diego", statement_id).status is Status.INSUFFICIENT_DATA
    assert services.statements.list_statements("diego").data == ()


@pytest.mark.parametrize("content", [b"", b"plain text, not a statement"])
def test_unreadable_files_are_invalid_input_and_store_nothing(services, content):
    result = services.statements.import_statement("camila", content)
    assert result.status is Status.INVALID_INPUT and result.field == "file"
    assert services.statements.list_statements("camila").data == ()


def test_pdf_of_an_unknown_bank_is_invalid_input(services):
    import pymupdf

    doc = pymupdf.open()
    doc.new_page().insert_text((40, 60), "BANCO DESCONOCIDO cartola FECHA DESCRIPCION SALDO", fontsize=9)
    result = services.statements.import_statement("camila", doc.tobytes())
    assert result.status is Status.INVALID_INPUT and "not a statement layout" in result.message


class _FailingReader:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def read(self, content: bytes):
        raise self.error


def _use_case(reader) -> StatementUseCases:
    return StatementUseCases(reader, InMemoryStatementStore(), InMemoryAuditLog(), FixedClock(datetime(2026, 10, 29, tzinfo=UTC)), SequentialIds())


def test_missing_ocr_is_insufficient_data_not_a_bad_file():
    result = _use_case(_FailingReader(StatementReaderUnavailable("this file needs OCR"))).import_statement("camila", b"%PDF-1.7 scan")
    assert result.status is Status.INSUFFICIENT_DATA and result.missing == ("statement_reader",)


def test_reader_errors_never_reach_the_store():
    use_case = _use_case(_FailingReader(StatementUnreadable("row without an amount")))
    assert use_case.import_statement("camila", b"%PDF-1.7").status is Status.INVALID_INPUT
    assert use_case.list_statements("camila").data == ()
