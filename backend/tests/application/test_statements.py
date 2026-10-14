"""Statement import end to end (container wiring, synthetic cartola): read → reconcile → store → audit."""

from __future__ import annotations

from datetime import UTC, datetime
from importlib.util import find_spec

import pytest

from neural_ledger.adapters.outbound.persistence.memory import InMemoryAuditLog, InMemoryStatementStore, InMemoryTransactionStore
from neural_ledger.adapters.outbound.system.clock import FixedClock
from neural_ledger.adapters.outbound.system.ids import SequentialIds
from neural_ledger.application.ports import StatementReaderUnavailable, StatementUnreadable
from neural_ledger.application.services.posting import LedgerPosting
from neural_ledger.application.use_cases.statements import StatementUseCases
from neural_ledger.domain.audit.events import AuditKind
from neural_ledger.domain.shared.envelope import Status
from tests.statement_samples import Sample, santander_pdf

pytest.importorskip("pymupdf")
pytest.importorskip("pdfplumber")
needs_ml = pytest.mark.skipif(find_spec("sklearn") is None, reason="the ml extra (scikit-learn) is not installed")

# The synthetic merchants are fictional, so the real classifier leaves charges uncategorized; which
# ones is the classifier's business (tests/adapters/test_classifier.py), not this file's.
CATEGORY_WARNINGS = {"UNCATEGORIZED_SPENDING"}


@needs_ml
def test_import_stores_a_verified_statement_and_audits_it(services):
    result = services.statements.import_statement("camila", santander_pdf())
    assert result.status is Status.OK
    assert result.data.imports[0].duplicate is False
    summary = result.data.imports[0].statement
    assert summary.verified and summary.issues == ()
    assert (summary.line_count, summary.total_debits, summary.total_credits) == (7, 61_080, 463_521)
    assert {w.code for w in result.warnings} <= CATEGORY_WARNINGS
    ledger = result.data.imports[0].ledger
    assert (ledger.posted, ledger.new) == (7, 7) and ledger.classifier.startswith("naive_bayes@")
    assert {f.key.rsplit(".", 1)[1]: f.value for f in result.facts}["closing_balance"] == 1_402_441

    listed = services.statements.list_statements("camila").data
    assert [s.statement_id for s in listed] == [summary.statement_id]
    events = [e for e in services.audit.raw() if e.draft.kind is AuditKind.STATEMENT_IMPORTED]
    assert len(events) == 1 and events[0].draft.execution_result == "VERIFIED" and events[0].draft.user_id == "camila"
    assert "posted=7 new=7" in events[0].draft.detail
    assert len(services.ledger.list_transactions("camila").data.transactions) == 7


@needs_ml
def test_reimport_is_a_duplicate_and_stores_nothing_new(services):
    first = services.statements.import_statement("camila", santander_pdf())
    again = services.statements.import_statement("camila", santander_pdf())
    assert again.data.imports[0].duplicate is True
    assert again.data.imports[0].statement.statement_id == first.data.imports[0].statement.statement_id
    assert {w.code for w in again.warnings} - CATEGORY_WARNINGS == {"DUPLICATE_STATEMENT"}
    assert (again.data.imports[0].ledger.posted, again.data.imports[0].ledger.new) == (7, 0)
    assert len(services.statements.list_statements("camila").data) == 1
    assert len(services.ledger.list_transactions("camila").data.transactions) == 7


def test_statement_that_does_not_add_up_is_stored_unverified_with_a_warning(services):
    result = services.statements.import_statement("camila", santander_pdf(Sample(daily_override={"04/12": 1_154_942})))
    assert result.status is Status.OK
    assert result.data.imports[0].statement.verified is False
    assert {i.code for i in result.data.imports[0].statement.issues} == {"DAILY_BALANCE"}
    unverified, not_posted = result.warnings
    assert unverified.code == "STATEMENT_UNVERIFIED" and "DAILY_BALANCE" in unverified.message
    assert not_posted.code == "NOT_POSTED" and "does not reconcile" in not_posted.message
    assert result.data.imports[0].ledger.posted == 0 and result.data.imports[0].ledger.classifier is None
    assert services.ledger.list_transactions("camila").data.transactions == ()

    detail = services.statements.get_statement("camila", result.data.imports[0].statement.statement_id)
    assert [w.code for w in detail.warnings] == ["STATEMENT_UNVERIFIED"]


def test_detail_wraps_descriptions_as_untrusted_and_is_scoped_to_the_owner(services):
    statement_id = services.statements.import_statement("camila", santander_pdf()).data.imports[0].statement.statement_id
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


class _KeywordClassifier:
    """Deterministic stand-in: 'SH0P' is shopping, anything else is a coin toss."""

    name = "keywords@test"

    def classify(self, descriptions):
        from neural_ledger.domain.ledger.categorization import CategoryGuess

        return tuple(CategoryGuess("shopping", 0.9) if "SH0P" in d else CategoryGuess("dining", 0.5 - 1e-9) for d in descriptions)


def _use_case(reader, classifier=None, transactions=None) -> StatementUseCases:
    posting = LedgerPosting(classifier or _KeywordClassifier(), transactions if transactions is not None else InMemoryTransactionStore())
    return StatementUseCases(
        reader, InMemoryStatementStore(), posting, InMemoryAuditLog(), FixedClock(datetime(2026, 10, 29, tzinfo=UTC)), SequentialIds()
    )


class _FixedReader:
    def __init__(self, statement) -> None:
        self.statement = statement

    def read(self, content: bytes):
        return (self.statement,)


def test_low_ocr_confidence_warns_about_descriptions_but_does_not_unverify():
    from dataclasses import replace
    from datetime import date

    from neural_ledger.domain.statements.model import BankStatement, DailyBalance, StatementLine, StatementSummary

    statement = BankStatement(
        "test", "0-000-00-00000-0", "CLP", date(2026, 9, 1), date(2026, 9, 30),
        (StatementLine(0, date(2026, 9, 2), "Compra SH0P", -3_280, confidence=0.21), StatementLine(1, date(2026, 9, 3), "PAGO", 10_000, confidence=0.93)),
        StatementSummary(100_000, 3_280, 10_000, 106_720),
        (DailyBalance(date(2026, 9, 3), 106_720),),
        source="ocr",
    )  # fmt: skip
    result = _use_case(_FixedReader(statement)).import_statement("camila", b"%PDF-1.7 scan")
    assert result.data.imports[0].statement.verified is True
    (warning,) = result.warnings
    assert warning.code == "OCR_LOW_CONFIDENCE" and warning.message.startswith("1 of 2 lines")

    broken = replace(statement, summary=replace(statement.summary, total_credits=10_001))
    codes = [w.code for w in _use_case(_FixedReader(broken)).import_statement("camila", b"%PDF-1.7 scan").warnings]
    assert codes == ["STATEMENT_UNVERIFIED", "OCR_LOW_CONFIDENCE", "NOT_POSTED"]


def test_missing_ocr_is_insufficient_data_not_a_bad_file():
    result = _use_case(_FailingReader(StatementReaderUnavailable("this file needs OCR"))).import_statement("camila", b"%PDF-1.7 scan")
    assert result.status is Status.INSUFFICIENT_DATA and result.missing == ("statement_reader",)


def test_reader_errors_never_reach_the_store():
    use_case = _use_case(_FailingReader(StatementUnreadable("row without an amount")))
    assert use_case.import_statement("camila", b"%PDF-1.7").status is Status.INVALID_INPUT
    assert use_case.list_statements("camila").data == ()


def test_cli_import_and_list(services, tmp_path, capsys):
    from neural_ledger.adapters.inbound.cli.commands import main

    path = tmp_path / "cartola.pdf"
    path.write_bytes(santander_pdf())
    assert main(services, ["import-statement", str(path), "--user", "camila"]) == 0
    out = capsys.readouterr().out
    assert "santander_cl_cuentamatica" in out and "VERIFIED" in out and "7 movements" in out
    assert main(services, ["statements", "--user", "camila"]) == 0
    assert "VERIFIED" in capsys.readouterr().out
    assert main(services, ["transactions", "--user", "camila"]) == 0
    out = capsys.readouterr().out
    if find_spec("sklearn"):
        assert "Compra Nacional MD SHOP ONE" in out and "income" in out
    else:
        assert "no transactions yet" in out
    assert main(services, ["import-statement", str(tmp_path / "missing.pdf")]) == 2
