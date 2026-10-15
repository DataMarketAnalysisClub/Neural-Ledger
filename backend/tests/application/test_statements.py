"""Statement import end to end (container wiring, synthetic cartola): read → reconcile → store → audit."""

from __future__ import annotations

from datetime import UTC, datetime
from importlib.util import find_spec

import pytest

from neural_ledger.adapters.outbound.persistence.memory import InMemoryAuditLog, InMemoryStatementStore, InMemoryTransactionStore
from neural_ledger.adapters.outbound.privacy.null import NullDetector
from neural_ledger.adapters.outbound.system.clock import FixedClock
from neural_ledger.adapters.outbound.system.ids import SequentialIds
from neural_ledger.application.ports import StatementReaderUnavailable, StatementUnreadable
from neural_ledger.application.services.posting import LedgerPosting
from neural_ledger.application.services.redaction import StatementRedactor
from neural_ledger.application.use_cases.statements import RedactionView, StatementUseCases
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
    facts = {f.key.rsplit(".", 1)[1]: f.value for f in result.facts}
    assert facts["closing_balance"] == 1_402_441
    # The sample's only personal data: the 10-digit ids Santander prints before transfers and payments.
    assert result.data.imports[0].redaction == RedactionView("pii-0.1", "none", False, {"NUMBER": 3}) and facts["redacted"] == 3
    assert summary.account_ref == "****3456"

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
    assert again.data.imports[0].duplicate is True and again.data.imports[0].redaction is None
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


def _use_case(reader, classifier=None, transactions=None, detector=None, store=None, audit=None) -> StatementUseCases:
    posting = LedgerPosting(classifier or _KeywordClassifier(), transactions if transactions is not None else InMemoryTransactionStore())
    return StatementUseCases(
        reader,
        StatementRedactor(detector or NullDetector()),
        store if store is not None else InMemoryStatementStore(),
        posting,
        audit if audit is not None else InMemoryAuditLog(),
        FixedClock(datetime(2026, 10, 29, tzinfo=UTC)),
        SequentialIds(),
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


def _statement_with_personal_data():
    """Fictional people, RUT, account and address, as a Santander cartola prints them."""
    from datetime import date

    from neural_ledger.domain.statements.model import BankStatement, DailyBalance, StatementLine, StatementSummary

    return BankStatement(
        "test", "0-000-00-12345-6", "CLP", date(2026, 9, 1), date(2026, 9, 30),
        (
            StatementLine(0, date(2026, 9, 2), "0000000003 Transf a JUAN PEREZ 11.111.111-1", -40_000, "2441010", "401"),
            StatementLine(1, date(2026, 9, 3), "TEF DE MARIA SOTO maria.soto@mail.cl", 10_000, None, "90"),
        ),
        StatementSummary(100_000, 40_000, 10_000, 70_000),
        (DailyBalance(date(2026, 9, 3), 70_000),),
    )  # fmt: skip


def test_import_redacts_before_anything_is_stored_posted_or_audited():
    store, audit, transactions = InMemoryStatementStore(), InMemoryAuditLog(), InMemoryTransactionStore()
    use_case = _use_case(_FixedReader(_statement_with_personal_data()), transactions=transactions, store=store, audit=audit)
    result = use_case.import_statement("camila", b"%PDF-1.7")
    assert result.status is Status.OK and result.data.imports[0].statement.verified
    assert result.data.imports[0].statement.account_ref == "****3456"
    assert result.data.imports[0].redaction == RedactionView("pii-0.1", "none", False, {"PERSON": 2, "ID": 1, "NUMBER": 1, "EMAIL": 1})

    (stored,) = store.for_user("camila")
    clean = ["[NUMBER] Transf a [PERSON] [ID]", "TEF DE [PERSON] [EMAIL]"]
    assert [line.description for line in stored.statement.lines] == clean
    assert stored.statement.account_ref == "****3456"
    kept = [(line.amount, line.reference, line.branch) for line in stored.statement.lines]
    assert kept == [(-40_000, "2441010", "401"), (10_000, None, "90")]  # amounts, document number and branch
    posted = transactions.for_user("camila")
    assert [p.transaction.merchant_raw for p in posted] == clean
    assert {p.transaction.account_id for p in posted} == {"test:****3456"}

    (event,) = audit.events()
    assert "redacted=5 detector=none posted=2" in event.draft.detail
    for personal in ("JUAN", "PEREZ", "MARIA", "SOTO", "11.111.111", "maria.soto", "12345"):
        assert personal not in event.draft.detail


# ---- redaction flows (ADR-028): duplicates, a detector that is down, a redaction that crashes --------


class _CountingDetector:
    name = "counting"

    def __init__(self) -> None:
        self.calls = 0

    def detect(self, texts):
        self.calls += 1
        return tuple(() for _ in texts)


class _DownDetector:
    name = "down"

    def detect(self, texts):
        from neural_ledger.application.ports import DetectorUnavailable

        raise DetectorUnavailable("HTTP 503")


class _BuggyDetector:
    name = "buggy"

    def detect(self, texts):
        raise RuntimeError(f"cannot parse {texts[0]!r}")  # an error message that quotes the statement


def test_the_statement_id_is_still_the_hash_of_the_statement_as_read():
    from dataclasses import replace

    from neural_ledger.domain.shared.hashing import content_id

    raw = _statement_with_personal_data()
    store = InMemoryStatementStore()
    first = _use_case(_FixedReader(raw), store=store).import_statement("camila", b"%PDF-1.7")
    assert first.data.imports[0].statement.statement_id == content_id(
        "stmt", "camila", raw.bank, raw.account_ref, raw.currency, raw.period_start, raw.period_end, raw.lines
    )
    # Two cartolas that differ only in personal data redact to the same text, yet stay two statements.
    lines = (replace(raw.lines[0], description=raw.lines[0].description.replace("JUAN PEREZ", "ANA ROJAS")), *raw.lines[1:])
    second = _use_case(_FixedReader(replace(raw, lines=lines)), store=store).import_statement("camila", b"%PDF-1.7")
    assert second.data.imports[0].duplicate is False and second.data.imports[0].statement.statement_id != first.data.imports[0].statement.statement_id
    stored = [[line.description for line in s.statement.lines] for s in store.for_user("camila")]
    assert len(stored) == 2 and stored[0] == stored[1]


def test_a_duplicate_is_still_detected_and_never_redacted_or_sent_to_the_detector_again():
    detector, store, audit = _CountingDetector(), InMemoryStatementStore(), InMemoryAuditLog()
    use_case = _use_case(_FixedReader(_statement_with_personal_data()), detector=detector, store=store, audit=audit)
    first = use_case.import_statement("camila", b"%PDF-1.7")
    again = use_case.import_statement("camila", b"%PDF-1.7")
    assert again.status is Status.OK and again.data.imports[0].duplicate is True and again.data.imports[0].redaction is None
    assert again.data.imports[0].statement.statement_id == first.data.imports[0].statement.statement_id
    assert len(store.for_user("camila")) == 1 and detector.calls == 1
    assert [w.code for w in again.warnings][-1] == "DUPLICATE_STATEMENT"
    assert [e.draft.execution_result for e in audit.events()] == ["VERIFIED", "DUPLICATE"]
    assert "redacted=" not in audit.events()[1].draft.detail


def test_a_detector_that_is_down_gives_a_degraded_import_still_redacted_by_the_rules(caplog):
    store, audit = InMemoryStatementStore(), InMemoryAuditLog()
    use_case = _use_case(_FixedReader(_statement_with_personal_data()), detector=_DownDetector(), store=store, audit=audit)
    with caplog.at_level("WARNING"):
        result = use_case.import_statement("camila", b"%PDF-1.7")
    assert result.status is Status.OK and result.data.imports[0].statement.verified
    assert (result.data.imports[0].redaction.detector, result.data.imports[0].redaction.degraded) == ("down", True)
    (degraded,) = [w for w in result.warnings if w.code == "REDACTION_DEGRADED"]
    assert "rules only" in degraded.message and "down" in degraded.message
    (stored,) = store.for_user("camila")
    assert [line.description for line in stored.statement.lines] == ["[NUMBER] Transf a [PERSON] [ID]", "TEF DE [PERSON] [EMAIL]"]
    assert "redacted=5 detector=down degraded=yes" in audit.events()[0].draft.detail
    assert "HTTP 503" in caplog.text


@pytest.mark.parametrize("where", ["detector", "rules"])
def test_a_redaction_crash_rejects_the_import_and_writes_nothing(where, monkeypatch, caplog):
    if where == "rules":
        from neural_ledger.application.services import redaction

        def crash(text):
            raise ValueError(f"bad rule on {text!r}")

        monkeypatch.setattr(redaction, "find_spans", crash)
    store, audit, transactions = InMemoryStatementStore(), InMemoryAuditLog(), InMemoryTransactionStore()
    detector = _BuggyDetector() if where == "detector" else None
    use_case = _use_case(
        _FixedReader(_statement_with_personal_data()), detector=detector, transactions=transactions, store=store, audit=audit
    )
    with caplog.at_level("DEBUG"):
        result = use_case.import_statement("camila", b"%PDF-1.7")
    assert result.status is Status.INSUFFICIENT_DATA and result.missing == ("redaction",)
    assert "not stored" in result.message and result.data is None
    assert store.for_user("camila") == () and transactions.for_user("camila") == () and audit.events() == ()
    assert ("RuntimeError" if where == "detector" else "ValueError") in caplog.text
    assert "JUAN" not in caplog.text and "Transf" not in caplog.text  # the error's type only, never its message


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
    assert "checking ****3456" in out and "personal data hidden: 3 NUMBER (rules pii-0.1, detector none)" in out
    assert main(services, ["statements", "--user", "camila"]) == 0
    assert "VERIFIED" in capsys.readouterr().out
    assert main(services, ["transactions", "--user", "camila"]) == 0
    out = capsys.readouterr().out
    if find_spec("sklearn"):
        assert "Compra Nacional MD SHOP ONE" in out and "income" in out
    else:
        assert "no transactions yet" in out
    assert main(services, ["import-statement", str(tmp_path / "missing.pdf")]) == 2
